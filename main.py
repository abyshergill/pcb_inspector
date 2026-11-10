import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
import config


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PCB Inspector")
    app.setWindowIcon(QIcon(config.ICON_PATH))  # default icon for all windows/dialogs

    # Import after QApplication exists and the splash is up, so heavy
    # imports (OpenCV, OCR) happen while the splash screen is visible.
    from ui.splash_screen import show_splash
    splash = show_splash(app)

    from ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    splash.finish(window)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
