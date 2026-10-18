"""Launch the desktop app: python app.py --demo (zero API credits)."""
import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="offline sample translations; no API calls")
    parser.add_argument("--smoke-test", action="store_true", help="offscreen window check; exits automatically")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        args.demo = True
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from translator.config import Settings, data_dir, load_environment
    from translator.gui import Window
    load_environment()
    app = QApplication(sys.argv[:1])
    if args.smoke_test and os.name == "nt":
        # Qt's offscreen backend does not enumerate Windows fonts automatically.
        # Use installed OS fonts only; do not redistribute font files.
        for filename in ("segoeui.ttf", "msyh.ttc"):
            QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + filename)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Dota Chat")
    try:
        settings = Settings() if args.smoke_test else Settings.load(data_dir() / "settings.json")
    except (ValueError, OSError):
        print("Settings could not be read. Original settings retained; using defaults.")
        settings = Settings()
    window = Window(settings, demo=args.demo, local_path=data_dir() / "smoke" if args.smoke_test else None)
    window.show()
    if args.smoke_test:
        def check():
            if window.feed.rowCount() < 4:
                print("SMOKE FAILED: demo rows not received")
                app.exit(1)
                window.worker.stop()
                return
            window.grab().save(str(window.local / "window-preview.png"))
            window.overlay.show()
            window.overlay.grab().save(str(window.local / "overlay-preview.png"))
            for index, name in ((1, "outgoing"), (2, "settings")):
                window.tabs.setCurrentIndex(index)
                app.processEvents()
                window.grab().save(str(window.local / f"{name}-preview.png"))
            print("SMOKE OK: normal window rendered, four labeled demo rows; no paid API used")
            window.quit()
        QTimer.singleShot(5000, check)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
