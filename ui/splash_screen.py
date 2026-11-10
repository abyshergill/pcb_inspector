import time
from PySide6.QtWidgets import QSplashScreen, QApplication
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt
import config


def show_splash(app: QApplication) -> QSplashScreen:
    # Previously two splash screens were created and the loading message
    # was put on the first one, which was never shown. Build it once.
    pixmap = QPixmap(config.SPLASH_PATH)
    if pixmap.isNull():
        pixmap = QPixmap(600, 350)
        pixmap.fill(QColor("#1e1e1e"))
    else:
        pixmap = pixmap.scaled(600, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.show()
    splash.showMessage(
        "Loading PCB Inspection System...",
        Qt.AlignBottom | Qt.AlignHCenter, Qt.white
    )
    app.processEvents()

    start = time.monotonic()
    while time.monotonic() - start < config.SPLASH_MIN_DURATION_SECONDS:
        app.processEvents()
        time.sleep(0.03)

    return splash
