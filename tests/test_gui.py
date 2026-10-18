import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "Install requirements for desktop checks")
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        if os.name == "nt":
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")

    def wait_until(self, predicate, seconds=6):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_demo_window_outgoing_overlay_and_cache_controls(self):
        from translator.config import Settings
        from translator.gui import Window
        with tempfile.TemporaryDirectory() as d, patch("translator.gui.data_dir", return_value=Path(d)):
            window = Window(Settings(), demo=True)
            try:
                window.show()
                self.wait_until(lambda: window.feed.rowCount() == 4)
                self.assertTrue(all("DEMO SAMPLE" in window.feed.item(i, 0).text() for i in range(4)))
                window.tabs.setCurrentIndex(1)
                window.outgoing_translate()
                self.wait_until(lambda: not window.outgoing_pending)
                self.assertTrue(window.copy_button.isEnabled())
                self.assertIn("Пушим", window.outgoing_result.toPlainText())
                # Copy result is an explicit button operation. Restore test clipboard.
                original_clipboard = self.app.clipboard().text()
                try:
                    window.copy_outgoing()
                    self.assertEqual(self.app.clipboard().text(), window.outgoing_result.toPlainText())
                finally:
                    self.app.clipboard().setText(original_clipboard)
                window.outgoing_input.setPlainText("different text")
                self.assertFalse(window.copy_button.isEnabled())
                window.outgoing_translate()
                self.wait_until(lambda: not window.outgoing_pending)
                self.assertFalse(window.copy_button.isEnabled())
                self.assertEqual(window.outgoing_result.toPlainText(), "different text")
                window.toggle_overlay()
                self.assertTrue(window.overlay.isVisible())
                flags = window.overlay.windowFlags()
                self.assertTrue(flags & Qt.WindowType.WindowTransparentForInput)
                self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
                self.assertIn("Take Roshan first", window.overlay.text.toPlainText())
                window.toggle_lock()
                self.assertFalse(window.overlay.locked)
                self.assertFalse(window.overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput)
                window.toggle_lock()
                self.assertTrue(window.overlay.locked)
                window.clear_display()
                self.assertEqual(window.feed.rowCount(), 0)
                self.assertEqual(window.history, [])
            finally:
                window.quit()
                window.worker.join(timeout=5)
                self.assertFalse(window.worker.is_alive())
                window.close()
                self.app.processEvents()

    def test_old_provider_key_is_not_reused_for_openai(self):
        from translator.config import Settings
        from translator.core import OpenAITranslator
        from translator.gui import Window
        with tempfile.TemporaryDirectory() as d, patch.dict("os.environ", {
                "OPENAI_API_KEY": "", "GEMINI_API_KEY": "old-provider-test-placeholder"}):
            window = Window(Settings(), local_path=Path(d))
            try:
                self.assertIsInstance(window.worker.api, OpenAITranslator)
                self.assertEqual(window.worker.api.key, "")
                window.poll()
                self.assertIn("OpenAI API key missing", window.status.text())
            finally:
                window.quit()
                window.worker.join(timeout=3)
                window.close()
                self.app.processEvents()
