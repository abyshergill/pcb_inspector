from dataclasses import dataclass, field
import config


@dataclass
class AppSettings:
    """Shared, mutable runtime settings referenced by multiple tabs.
    Defaults are read from config when an instance is created (not when
    this module is imported), so config overrides are always honoured."""
    pass_dir: str = field(default_factory=lambda: config.PASS_DIR)
    fail_dir: str = field(default_factory=lambda: config.FAIL_DIR)
    golden_image_dir: str = field(default_factory=lambda: config.GOLDEN_IMAGE_DIR)
    logging_dir: str = field(default_factory=lambda: config.LOGGING_DIR)
    tesseract_path: str = field(default_factory=lambda: config.TESSERACT_PATH)
