from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def ensure_bgr(image: np.ndarray) -> np.ndarray:
    """
    Normalizes any incoming frame to 3-channel, 8-bit BGR, regardless of
    what the camera/SDK handed back:
      - None                -> returned as-is (caller must handle)
      - 16-bit (mono16/BGR16) -> scaled down to 8-bit first
      - 1 channel (mono8/mono/grayscale) -> converted to BGR
      - 3 channels (already BGR)         -> returned as-is
      - 4 channels (BGRA/RGBA)           -> alpha dropped, converted to BGR
      - anything else                    -> raises a clear error instead of
                                             letting OpenCV fail cryptically
    """
    if image is None:
        return image

    if image.dtype != np.uint8:
        image = _to_8bit(image)

    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    if image.ndim != 3:
        raise ValueError(f"Unsupported image shape: {image.shape}.")

    channels = image.shape[2]
    if channels == 1:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if channels == 3:
        return image
    if channels == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    raise ValueError(f"Unsupported image channel count: {channels}. "
                      f"Expected 1 (mono), 3 (BGR/RGB), or 4 (BGRA/RGBA).")


def _to_8bit(image: np.ndarray) -> np.ndarray:
    """Rescales 16-bit (or other bit-depth) sensor data down to 8-bit,
    since OpenCV's color-conversion and JPEG writers expect uint8."""
    if image.dtype == np.bool_:
        return image.astype(np.uint8) * 255
    img_min, img_max = float(image.min()), float(image.max())
    if img_max <= img_min:
        # Constant frame: clip instead of letting e.g. 4000 wrap around to 160.
        return np.clip(image, 0, 255).astype(np.uint8)
    scaled = (image.astype(np.float32) - img_min) / (img_max - img_min) * 255.0
    return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)


def bayer_to_bgr(image: np.ndarray, pattern: str = "BG") -> np.ndarray:
    """
    Debayers a raw single-channel Bayer frame into BGR. Only call this for
    cameras explicitly configured in Bayer/raw mode (e.g. some GigE Vision
    sensors) — do NOT run this on already-color or mono8 frames.
    pattern: one of "BG", "GB", "RG", "GR" (check your camera's datasheet).
    """
    pattern_map = {
        "BG": cv2.COLOR_BayerBG2BGR,
        "GB": cv2.COLOR_BayerGB2BGR,
        "RG": cv2.COLOR_BayerRG2BGR,
        "GR": cv2.COLOR_BayerGR2BGR,
    }
    if pattern not in pattern_map:
        raise ValueError(f"Unknown Bayer pattern '{pattern}'. Use BG, GB, RG, or GR.")
    if image.dtype != np.uint8:
        image = _to_8bit(image)
    return cv2.cvtColor(image, pattern_map[pattern])


def read_image(path, flags: int = cv2.IMREAD_COLOR) -> Optional[np.ndarray]:
    """cv2.imread replacement that also works with non-ASCII paths
    (cv2.imread silently returns None for those on Windows)."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def write_image(path, image: np.ndarray) -> None:
    """cv2.imwrite replacement that works with non-ASCII paths and raises
    instead of silently returning False when the write fails."""
    path = Path(path)
    ext = path.suffix or ".jpg"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise IOError(f"Could not encode image as '{ext}' for {path}")
    try:
        buf.tofile(str(path))
    except OSError as exc:
        raise IOError(f"Could not write image to {path}: {exc}") from exc
