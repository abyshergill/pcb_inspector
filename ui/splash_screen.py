import time
from PySide6.QtWidgets import QSplashScreen, QApplication
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import config

def show_splash(app: QApplication) -> QSplashScreen:
    pixmap = QPixmap(config.SPLASH_PATH)
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.showMessage(
        "Loading PCB Inspection System...",
        Qt.AlignBottom | Qt.AlignHCenter, Qt.white
    )
    pixmap = QPixmap(config.SPLASH_PATH)
    pixmap = pixmap.scaled(600, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.show()

    app.processEvents()

    start = time.time()
    while time.time() - start < config.SPLASH_MIN_DURATION_SECONDS:
        app.processEvents()
        time.sleep(0.03)

    return splash
