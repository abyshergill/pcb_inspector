import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow
from ui.splash_screen import show_splash
import config

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(config.ICON_PATH))  # default icon for all windows/dialogs

    splash = show_splash(app)

    window = MainWindow()
    window.show()
    splash.finish(window)

    sys.exit(app.exec())
