from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QSizeGrip, QTextBrowser, QVBoxLayout, QHBoxLayout


class Overlay(QFrame):
    def __init__(self, settings, demo=False):
        super().__init__(None)
        self.locked, self.demo, self.drag_offset = True, demo, None
        self.notice = ""
        self.setWindowTitle("Dota Chat overlay")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(300, 120)
        self.setGeometry(*settings.overlay_geometry)
        if not any(screen.availableGeometry().intersects(self.geometry()) for screen in QApplication.screens()):
            self.move(QApplication.primaryScreen().availableGeometry().topLeft())
        self.setStyleSheet("QFrame { background: rgba(12, 22, 32, 210); border: 1px solid #3b6b7b; border-radius: 8px; }"
                           "QLabel { color: #88d8ce; background: transparent; border: 0; padding: 4px; }"
                           "QTextBrowser { background: transparent; border: 0; color: #edf7ff; }")
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title)
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.setOpenExternalLinks(False)
        self.text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.text, 1)
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)
        self.grip.hide()
        bottom.addWidget(self.grip)
        layout.addLayout(bottom)
        self.render([], settings)

    def set_locked(self, locked):
        visible = self.isVisible()
        self.locked = locked
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, locked)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        self.grip.setVisible(not locked)
        self.update_title()
        if visible:
            self.show()  # WA_ShowWithoutActivating + WindowDoesNotAcceptFocus.

    def update_title(self):
        self.title.setText(("DEMO · " if self.demo else "Dota Chat · ") +
                           (self.notice or ("click-through · Ctrl+Alt+L to unlock" if self.locked else "UNLOCKED · drag here · resize corner")))

    def set_notice(self, text):
        self.notice = text
        self.update_title()

    def render(self, history, settings):
        self.update_title()
        self.setWindowOpacity(settings.opacity / 100)
        paragraphs = []
        for result in history[-6:]:
            message = result.job.message
            supplied = " · ".join(x for x in (message.sender, message.hero, message.channel) if x)
            identity = f'<span style="color:#83c9c4">{escape(supplied)}</span><br>' if supplied else ""
            translated = escape(result.translation).replace("\n", "<br>")
            original = escape(message.text).replace("\n", "<br>")
            paragraphs.append(f'<p>{identity}<b>{translated}</b><br>'
                              f'<span style="font-size:{max(10, settings.font_size-3)}px;color:#a8bac9">{original}</span></p>')
        content = "".join(paragraphs) or '<p style="color:#a8bac9">Waiting for translated messages…</p>'
        self.text.setHtml(f'<div style="font-family:Segoe UI;font-size:{settings.font_size}px;color:#edf7ff">{content}</div>')
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())

    def mousePressEvent(self, event):
        if not self.locked and event.button() == Qt.MouseButton.LeftButton and event.position().y() < 50:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and not self.locked:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)
