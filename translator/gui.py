from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import QMimeData, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStyle, QSystemTrayIcon, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from translator.config import Settings, data_dir
from translator.core import Duplicates, Gemini, Job, Message, Result, TARGETS, Worker
from translator.demo import DemoApi, SAMPLES
from translator.ingest import Mapping, Receiver, checked_path, discover_strings
from translator.outgoing import ClipboardGuard

STYLE = """
QWidget { background: #101923; color: #e3edf6; font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QDialog { background: #101923; }
QLabel#title { font-size: 27px; font-weight: 700; color: #f3f8fc; }
QLabel#muted { color: #9bb0c3; }
QPushButton { background: #22364a; border: 1px solid #34526c; border-radius: 6px; padding: 8px 14px; }
QPushButton:hover { background: #2d4963; }
QPushButton:disabled { color: #6d7e8c; background: #192633; }
QPushButton#primary { background: #166a65; border-color: #278f87; }
QLineEdit, QTextEdit, QSpinBox, QComboBox { background: #172635; border: 1px solid #34526c; border-radius: 5px; padding: 6px; }
QTableWidget { background: #111e2a; alternate-background-color: #172635; border: 1px solid #2c4053; gridline-color: #23374a; }
QHeaderView::section { background: #1e3143; color: #a9c1d5; padding: 9px; border: 0; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: #172635; padding: 10px 20px; margin-right: 4px; }
QTabBar::tab:selected { background: #234858; color: #8fe2d6; }
QMenu { background: #1e3143; }
"""


class Bridge(QObject):
    result = Signal(object)


class FieldPicker(QDialog):
    def __init__(self, snapshot, parent):
        super().__init__(parent)
        self.setWindowTitle("Choose the actual GSI message field")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        label = QLabel("Local payload preview. Find a chat message you recognize and select its field.\n"
                       "Values remain in memory. Nothing here establishes sender or channel identity.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Observed field path (JSON array)", "Local string preview"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.paths = []
        for path, value in discover_strings(snapshot):
            if len(self.paths) >= 500:
                break
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(json.dumps(path, ensure_ascii=False)))
            self.table.setItem(row, 1, QTableWidgetItem(value[:300]))
            self.paths.append(path)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class Window(QMainWindow):
    def __init__(self, settings: Settings, demo=False, local_path=None):
        super().__init__()
        self.settings, self.demo = settings, demo
        self.local = Path(local_path) if local_path else data_dir()
        self.local.mkdir(parents=True, exist_ok=True)
        self.latest_snapshot = None
        self.receiver, self.overlay, self.hotkeys = None, None, None
        self.receiver_error = ""
        self.history = []
        self.outgoing_pending = False
        self.outgoing_context = None
        self.clipboard_guard = ClipboardGuard()
        self.pending_clipboard_restore = None
        self.overflow_duplicates = Duplicates()
        self.quitting = False
        self.setWindowTitle("Dota Chat · " + ("OFFLINE DEMO" if demo else "Personal translator"))
        self.resize(1100, 760)
        self.setStyleSheet(STYLE)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        body = QWidget()
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Dota Chat")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("English translations · your key · local control")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        self.mode_label = QLabel("OFFLINE DEMO · labeled sample chat · no API requests" if demo else
                                 "GSI input assumed usable · chat field mapping / incoming feed not yet verified")
        self.mode_label.setWordWrap(True)
        layout.addWidget(self.mode_label)
        toolbar = QHBoxLayout()
        self.overlay_button = QPushButton("Show overlay")
        self.overlay_button.setEnabled(False)
        self.lock_button = QPushButton("Unlock overlay")
        self.lock_button.setEnabled(False)
        self.sample_button = QPushButton("Load sample chat" if demo else "Inspect GSI chat field")
        self.sample_button.setObjectName("primary")
        self.sample_button.clicked.connect(self.load_samples if demo else self.pick_field)
        self.clear_button = QPushButton("Clear display")
        self.clear_button.clicked.connect(self.clear_display)
        for widget in (self.sample_button, self.overlay_button, self.lock_button, self.clear_button):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.build_feed()
        self.build_outgoing()
        self.build_settings()
        self.status = QLabel("Starting translation worker…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bridge = Bridge()
        self.bridge.result.connect(self.receive_result)
        model = "offline-demo-v1" if demo else settings.model
        api = DemoApi() if demo else Gemini(os.environ.get("GEMINI_API_KEY", ""), settings.model)
        self.worker = Worker(self.local / ("demo-cache.sqlite" if demo else "translations.sqlite"),
                             api, self.bridge.result.emit, model, rpm=120 if demo else settings.rpm)
        self.worker.start()
        self.build_tray()
        self.setup_overlay()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self.save_metrics)
        self.metrics_timer.start(10000)
        if demo:
            QTimer.singleShot(100, self.load_samples)
        else:
            self.start_receiver()

    def build_feed(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.feed = QTableWidget(0, 4)
        self.feed.setHorizontalHeaderLabels(["Source / supplied identity", "Original", "English", "Status"])
        self.feed.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.feed.setWordWrap(True)
        self.feed.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.feed.setAlternatingRowColors(True)
        self.feed.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.feed.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.feed, 1)
        row = QHBoxLayout()
        self.manual = QLineEdit()
        self.manual.setPlaceholderText("Paste a message to translate into English")
        button = QPushButton("Translate")
        button.clicked.connect(self.manual_translate)
        self.manual.returnPressed.connect(self.manual_translate)
        row.addWidget(self.manual, 1)
        row.addWidget(button)
        layout.addLayout(row)
        self.tabs.addTab(page, "Incoming")

    def build_outgoing(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("Write English, choose a language, then translate and copy. You choose the Dota channel and paste manually.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.outgoing_input = QTextEdit()
        self.outgoing_input.setPlaceholderText("English message…")
        if self.demo:
            self.outgoing_input.setPlainText("Push mid after Roshan")
        layout.addWidget(self.outgoing_input)
        row = QHBoxLayout()
        self.target = QComboBox()
        self.target.addItems(["Russian", "Spanish", "Chinese"])
        self.outgoing_button = QPushButton("Translate outgoing")
        self.outgoing_button.setObjectName("primary")
        self.outgoing_button.clicked.connect(self.outgoing_translate)
        self.copy_button = QPushButton("Copy result")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_outgoing)
        for w in (self.target, self.outgoing_button, self.copy_button):
            row.addWidget(w)
        layout.addLayout(row)
        self.outgoing_result = QTextEdit()
        self.outgoing_result.setReadOnly(True)
        layout.addWidget(self.outgoing_result)
        self.outgoing_status = QLabel("Demo: only the displayed sample phrase is available." if self.demo else "Ready")
        self.outgoing_status.setWordWrap(True)
        layout.addWidget(self.outgoing_status)
        self.outgoing_input.textChanged.connect(lambda: self.copy_button.setEnabled(False))
        self.target.currentIndexChanged.connect(lambda: self.copy_button.setEnabled(False))
        self.tabs.addTab(page, "Outgoing")

    def build_settings(self):
        page = QWidget()
        form = QFormLayout(page)
        self.model_input = QLineEdit(self.settings.model)
        form.addRow("Gemini model (restart to apply)", self.model_input)
        self.rpm_input = QSpinBox()
        self.rpm_input.setRange(1, 120)
        self.rpm_input.setValue(self.settings.rpm)
        form.addRow("Maximum requests / minute (restart)", self.rpm_input)
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(self.settings.port)
        form.addRow("Local GSI port (restart / config must match)", self.port_input)
        self.font_input = QSpinBox()
        self.font_input.setRange(10, 40)
        self.font_input.setValue(self.settings.font_size)
        form.addRow("Overlay font size", self.font_input)
        self.opacity_input = QSpinBox()
        self.opacity_input.setRange(15, 100)
        self.opacity_input.setValue(self.settings.opacity)
        form.addRow("Overlay opacity %", self.opacity_input)
        self.mapping_enabled = QCheckBox("Translate only the explicitly mapped message field")
        self.mapping_enabled.setChecked(self.settings.mapping.enabled)
        form.addRow("GSI capture", self.mapping_enabled)
        self.path_inputs = {}
        for key in ("records", "text", "event_id", "sender", "hero", "channel", "chatwheel"):
            widget = QLineEdit(json.dumps(getattr(self.settings.mapping, key)))
            self.path_inputs[key] = widget
            form.addRow("Observed " + key + " path (JSON array)", widget)
        note = QLabel('Paths are selected from actual payloads. Use "*" for an array/object collection.\n'
                      'Identity/channel paths are optional. A blank event ID uses limited text deduplication.\n'
                      'No key is stored in settings. Set GEMINI_API_KEY in your environment or ignored .env.')
        note.setWordWrap(True)
        form.addRow(note)
        self.hotkey_check = QCheckBox("Enable foreground-Dota clipboard translation (Ctrl+Alt+Y; manual paste)")
        self.hotkey_check.setChecked(self.settings.outgoing_hotkey)
        form.addRow(self.hotkey_check)
        row = QHBoxLayout()
        save = QPushButton("Save settings")
        save.clicked.connect(self.save_settings)
        clear_cache = QPushButton("Clear translation cache")
        clear_cache.clicked.connect(self.clear_cache)
        row.addWidget(save)
        row.addWidget(clear_cache)
        form.addRow(row)
        self.settings_status = QLabel("Changes to model and rate take effect after restart.")
        self.settings_status.setWordWrap(True)
        form.addRow(self.settings_status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "Settings")

    def build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        for label, callback in (("Show app", self.showNormal), ("Hide app", self.hide), ("Quit", self.quit)):
            action = menu.addAction(label)
            action.triggered.connect(callback)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Dota Chat — " + ("offline demo" if self.demo else "personal translator"))
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def start_receiver(self):
        try:
            token = (self.local / "receiver-token.txt").read_text(encoding="utf-8").strip()
            if not token:
                raise ValueError()
            self.receiver = Receiver(token, self.settings.port)
            self.receiver.start()
        except (OSError, ValueError):
            self.receiver_error = "GSI unavailable: prepare config, close diagnostic receiver, then restart app"

    def pick_field(self):
        if self.latest_snapshot is None:
            self.settings_status.setText("No GSI payload yet. Start Dota with the diagnostic configuration enabled.")
            self.tabs.setCurrentIndex(2)
            return
        picker = FieldPicker(self.latest_snapshot, self)
        if picker.exec() == QDialog.DialogCode.Accepted:
            row = picker.table.currentRow()
            if row < 0:
                return
            path = picker.paths[row]
            if not path or path[-1] == "*":
                self.settings_status.setText("Choose an object field containing the chat text; array-string roots need a custom adapter.")
                return
            self.path_inputs["records"].setText(json.dumps(path[:-1]))
            self.path_inputs["text"].setText(json.dumps(path[-1:]))
            self.mapping_enabled.setChecked(True)
            self.save_settings()

    def manual_translate(self):
        text = self.manual.text()
        status = self.worker.submit(Job(Message(text, origin="demo" if self.demo else "manual")))
        if status == "queued":
            self.manual.clear()
        else:
            self.status.setText(status)

    def load_samples(self):
        for original, _ in SAMPLES:
            self.worker.submit(Job(Message(original, origin="DEMO SAMPLE")))

    def outgoing_translate(self):
        self.submit_outgoing(self.outgoing_input.toPlainText(), self.target.currentText())

    def submit_outgoing(self, text, target, context=None):
        if self.outgoing_pending:
            return False
        job = Job(Message(text, origin="demo outgoing" if self.demo else "outgoing"), target, outgoing=True)
        status = self.worker.submit(job)
        if status != "queued":
            self.outgoing_status.setText(status)
            return False
        self.outgoing_context = context
        if context is not None and self.overlay:
            self.overlay.set_notice("Translating clipboard → " + target)
        self.outgoing_pending = True
        self.outgoing_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.outgoing_status.setText("Translating…")
        return True

    def copy_outgoing(self):
        if self.copy_button.isEnabled():
            QApplication.clipboard().setText(self.outgoing_result.toPlainText())
            self.outgoing_status.setText("Copied. Paste manually into the Dota channel you selected.")

    def receive_result(self, result):
        if self.quitting:
            return
        if result.job.outgoing:
            self.outgoing_pending = False
            self.outgoing_button.setEnabled(True)
            self.outgoing_result.setPlainText(result.translation)
            self.outgoing_status.setText(result.job.target + " · " + result.status + f" · {result.latency_ms:.0f} ms")
            current = (self.outgoing_input.toPlainText() == result.job.message.text
                       and self.target.currentText() == result.job.target)
            self.copy_button.setEnabled(current and result.status in ("translated", "cached"))
            self.finish_hotkey(result)
            return
        self.history.append(result)
        self.history = self.history[-300:]
        if self.feed.rowCount() >= 300:
            self.feed.removeRow(0)
        row = self.feed.rowCount()
        self.feed.insertRow(row)
        message = result.job.message
        identity = message.origin
        if message.sender:
            identity += " · " + message.sender
        if message.hero:
            identity += " · " + message.hero
        if message.channel:
            identity += " · channel " + message.channel
        for col, text in enumerate((identity, message.text, result.translation, result.status)):
            self.feed.setItem(row, col, QTableWidgetItem(text))
        self.feed.resizeRowToContents(row)
        QTimer.singleShot(0, self.feed.resizeRowsToContents)
        self.feed.scrollToBottom()
        self.update_overlay()

    def poll(self):
        if self.receiver:
            snapshot = self.receiver.latest()
            if snapshot is not None:
                self.latest_snapshot = snapshot
                for message in self.settings.mapping.extract(snapshot):
                    status = self.worker.submit(Job(message))
                    if status == "queue full" and not self.overflow_duplicates.contains(message):
                        self.overflow_duplicates.add(message)
                        self.receive_result(Result(Job(message), message.text, "queue full — original shown"))
        metrics = self.worker.engine.metrics.copy() if self.worker.engine else {}
        if self.demo:
            connection = "OFFLINE DEMO"
        elif self.receiver_error:
            connection = self.receiver_error
        elif self.receiver:
            connected = time.monotonic() - self.receiver.last_received < 15
            connection = ("GSI receiving" if connected else "GSI waiting") + f" · {self.receiver.requests} payloads"
            if not self.settings.mapping.enabled:
                connection += " · select chat field"
        else:
            connection = "GSI stopped"
        key = os.environ.get("GEMINI_API_KEY", "")
        key_status = "" if self.demo or (key and key != "your_gemini_api_key_here") else " · API key missing"
        hotkey_status = ""
        if self.settings.outgoing_hotkey and not self.demo:
            hotkey_status = (" · Ctrl+Alt+Y → " + self.target.currentText()
                             if self.hotkeys and 0x4013 in self.hotkeys.registered else " · outgoing hotkey unavailable")
        self.status.setText(f"{connection}{key_status} · queue {self.worker.jobs.qsize()}/64 · "
                            f"requests {metrics.get('requests', 0)} · cached {metrics.get('cache_hits', 0)} · "
                            f"failed {metrics.get('failures', 0)} · {metrics.get('last_latency_ms', 0):.0f} ms "
                            + self.worker.error + hotkey_status)

    def save_settings(self):
        try:
            mapping = Mapping.from_dict({"enabled": self.mapping_enabled.isChecked(), **{
                key: json.loads(widget.text()) for key, widget in self.path_inputs.items()}})
            if mapping.enabled and not mapping.text:
                raise ValueError("Select a text field before enabling capture")
            model = self.model_input.text().strip()
            if not model or len(model) > 150:
                raise ValueError("Enter a valid model name")
            self.settings.model, self.settings.rpm = model, self.rpm_input.value()
            self.settings.port = self.port_input.value()
            self.settings.font_size, self.settings.opacity = self.font_input.value(), self.opacity_input.value()
            self.settings.mapping = mapping
            self.settings.outgoing_hotkey = self.hotkey_check.isChecked()
            if self.overlay:
                g = self.overlay.geometry()
                self.settings.overlay_geometry = [g.x(), g.y(), g.width(), g.height()]
            self.settings.save(self.local / "settings.json")
            if self.hotkeys:
                self.hotkeys.set_outgoing_enabled(self.settings.outgoing_hotkey and not self.demo)
            self.update_overlay()
            self.settings_status.setText("Saved. Mapping/overlay apply now; restart to change model/rate.")
        except (ValueError, OSError):
            self.settings_status.setText("Could not save: check JSON path arrays, text mapping, model and folder permissions.")

    def clear_cache(self):
        self.settings_status.setText("Cache clear queued." if self.worker.clear_cache() else "Queue is full; try again.")

    def save_metrics(self):
        if self.worker.engine:
            try:
                values = dict(self.worker.engine.metrics, dropped=self.worker.dropped,
                              queued=self.worker.jobs.qsize(), demo=self.demo)
                path = self.local / "metrics.json"
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(values, indent=2), encoding="utf-8")
                temporary.replace(path)
            except OSError:
                pass

    def clear_display(self):
        self.history.clear()
        self.feed.setRowCount(0)
        self.update_overlay()

    def setup_overlay(self):
        from translator.overlay import Overlay
        from translator.windows import Hotkeys
        self.overlay = Overlay(self.settings, self.demo)
        self.overlay_button.setEnabled(True)
        self.lock_button.setEnabled(True)
        self.overlay_button.clicked.connect(self.toggle_overlay)
        self.lock_button.clicked.connect(self.toggle_lock)
        self.hotkeys = Hotkeys(self.toggle_overlay, self.toggle_lock, self.hotkey_outgoing,
                               outgoing_enabled=self.settings.outgoing_hotkey and not self.demo)
        for label, callback in (("Show/hide overlay · Ctrl+Alt+T", self.toggle_overlay),
                                ("Lock/unlock overlay · Ctrl+Alt+L", self.toggle_lock)):
            self.tray.contextMenu().addAction(label).triggered.connect(callback)
        if self.hotkeys.failures:
            self.settings_status.setText("; ".join(self.hotkeys.failures) + ". Use buttons/tray instead.")

    def toggle_overlay(self):
        if self.overlay:
            self.overlay.setVisible(not self.overlay.isVisible())
            self.overlay_button.setText("Hide overlay" if self.overlay.isVisible() else "Show overlay")

    def toggle_lock(self):
        if self.overlay:
            self.overlay.set_locked(not self.overlay.locked)
            self.lock_button.setText("Unlock overlay" if self.overlay.locked else "Lock overlay")

    def update_overlay(self):
        if self.overlay:
            self.overlay.render(self.history, self.settings)

    def hotkey_outgoing(self):
        from translator.windows import clipboard_sequence, dota_foreground
        if self.demo or not self.settings.outgoing_hotkey or self.outgoing_pending or not dota_foreground():
            return
        sequence = clipboard_sequence()
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        context = self.clipboard_guard.begin(text, sequence, True)
        if context is None:
            return
        # Preserve a bounded copy of clipboard formats, without saving them to disk.
        mime = clipboard.mimeData()
        saved = {fmt: bytes(mime.data(fmt)) for fmt in mime.formats()} if mime else {}
        if (sum(map(len, saved.values())) > 1024 * 1024 or clipboard_sequence() != sequence
                or not dota_foreground()):
            self.outgoing_status.setText("Clipboard changed or is too large; use app text box and manual paste.")
            return
        context["saved_formats"] = saved
        self.submit_outgoing(text, self.target.currentText(), context)

    def finish_hotkey(self, result):
        from translator.windows import clipboard_sequence, dota_foreground
        context, self.outgoing_context = self.outgoing_context, None
        if context is None:
            return
        if result.status not in ("translated", "cached"):
            if self.overlay:
                self.overlay.set_notice("Outgoing failed · original kept · use app")
            return
        if not self.settings.outgoing_hotkey or not self.clipboard_guard.can_copy(context, clipboard_sequence(), dota_foreground()):
            self.outgoing_status.setText("Translation ready in app; clipboard/focus changed. Copy and paste manually.")
            self.copy_button.setEnabled(True)
            if self.overlay:
                self.overlay.set_notice("Outgoing ready in app · clipboard/focus changed")
            return
        QApplication.clipboard().setText(result.translation)
        self.clipboard_guard.copied(result.translation)
        translated_sequence = clipboard_sequence()
        self.pending_clipboard_restore = (translated_sequence, context["saved_formats"])
        self.outgoing_status.setText("Translation copied. Paste manually in your chosen channel. Prior clipboard restores in 30s if unchanged.")
        if self.overlay:
            self.overlay.set_notice("Outgoing copied · paste manually in chosen channel")
        def restore():
            self.restore_clipboard(translated_sequence, context["saved_formats"])
        QTimer.singleShot(30000, restore)

    def restore_clipboard(self, sequence, formats):
        from translator.windows import clipboard_sequence
        if clipboard_sequence() == sequence:
            mime = QMimeData()
            for fmt, value in formats.items():
                mime.setData(fmt, value)
            QApplication.clipboard().setMimeData(mime)
        if self.pending_clipboard_restore and self.pending_clipboard_restore[0] == sequence:
            self.pending_clipboard_restore = None

    def closeEvent(self, event):
        if not self.quitting and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.timer.stop()
        self.metrics_timer.stop()
        self.save_metrics()
        if self.pending_clipboard_restore:
            self.restore_clipboard(*self.pending_clipboard_restore)
        if self.overlay:
            g = self.overlay.geometry()
            self.settings.overlay_geometry = [g.x(), g.y(), g.width(), g.height()]
            try:
                self.settings.save(self.local / "settings.json")
            except OSError:
                pass
        self.worker.stop()
        if self.receiver:
            # Shutdown can block briefly; keep it off the GUI thread.
            import threading
            threading.Thread(target=self.receiver.stop, daemon=True).start()
        if self.overlay:
            self.overlay.close()
        if self.hotkeys:
            self.hotkeys.close()
        self.tray.hide()
        QApplication.quit()
