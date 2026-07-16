from dataclasses import dataclass
import config

@dataclass
class AppSettings:
    """Shared, mutable runtime settings referenced by multiple tabs."""
    pass_dir: str = config.PASS_DIR
    fail_dir: str = config.FAIL_DIR
    golden_image_dir: str = config.GOLDEN_IMAGE_DIR
    logging_dir: str = config.LOGGING_DIR
    tesseract_path: str = config.TESSERACT_PATH
