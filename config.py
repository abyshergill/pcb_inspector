from pathlib import Path

# All default paths are resolved against the project folder, so the app
# behaves the same no matter which working directory it is launched from.
BASE_DIR = Path(__file__).resolve().parent

PASS_DIR = str(BASE_DIR / "output" / "pass")
FAIL_DIR = str(BASE_DIR / "output" / "fail")
GOLDEN_IMAGE_DIR = str(BASE_DIR / "golden_images")
LOGGING_DIR = str(BASE_DIR / "logs")
TEMPLATES_DIR = str(BASE_DIR / "templates")
CAMERA_DEVICE_INDEX = 0

TESSERACT_PATH = ""  # e.g. "C:/Program Files/Tesseract-OCR/tesseract.exe" — leave blank to use EasyOCR automatically

ICON_PATH = str(BASE_DIR / "assets" / "icon.png")
SPLASH_PATH = str(BASE_DIR / "assets" / "splash.png")
SPLASH_MIN_DURATION_SECONDS = 1.5

LIVE_PREVIEW_INTERVAL_MS = 150

# Live triggers (auto capture / outbound / inbound) are dropped while this
# many inspections are still queued or running, so a fast trigger rate
# cannot pile up unbounded work and memory behind slow OCR/inspection.
MAX_PENDING_LIVE_INSPECTIONS = 4

# Timeout used when Mode 1 opens its TCP connection, so an unreachable host
# cannot freeze the GUI for the OS default (often 30-75 seconds).
NETWORK_CONNECT_TIMEOUT_S = 2.0
