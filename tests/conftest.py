import os
import sys
from pathlib import Path

import numpy as np
import pytest

# Run Qt without a display (CI, SSH sessions) unless the caller chose otherwise.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

import config  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Point every default output folder at a temp dir so tests never write
    into the real project folders."""
    for name in ("PASS_DIR", "FAIL_DIR", "GOLDEN_IMAGE_DIR", "LOGGING_DIR", "TEMPLATES_DIR"):
        monkeypatch.setattr(config, name, str(tmp_path / name.lower()))
    yield


def make_pcb_image(width: int = 320, height: int = 240, seed: int = 0) -> np.ndarray:
    """A synthetic, textured 'PCB' image with distinct, colourful components."""
    rng = np.random.default_rng(seed)
    img = np.full((height, width, 3), (30, 90, 20), dtype=np.uint8)  # green board
    noise = rng.integers(0, 25, size=(height, width, 1), dtype=np.uint8)
    img = cv2.add(img, np.repeat(noise, 3, axis=2))
    cv2.rectangle(img, (20, 20), (90, 80), (40, 40, 40), -1)            # chip
    for i in range(6):
        cv2.line(img, (25 + i * 11, 20), (25 + i * 11, 10), (200, 200, 200), 2)  # pins
    cv2.circle(img, (200, 60), 25, (0, 180, 255), -1)                   # capacitor (orange)
    cv2.circle(img, (200, 60), 10, (255, 255, 255), 2)
    cv2.rectangle(img, (140, 140), (300, 220), (180, 30, 30), -1)       # connector (blue)
    cv2.putText(img, "U1", (35, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


@pytest.fixture
def pcb_image():
    return make_pcb_image()


@pytest.fixture
def golden_path(tmp_path, pcb_image):
    path = tmp_path / "golden.png"
    cv2.imwrite(str(path), pcb_image)
    return path
