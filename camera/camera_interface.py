from abc import ABC, abstractmethod
import numpy as np
import cv2
from core.image_utils import ensure_bgr


class CameraInterface(ABC):
    """Abstract camera API — subclass this for a vendor SDK
    (Basler/Pylon, FLIR Spinnaker, GigE Vision, etc.)."""

    @abstractmethod
    def capture(self) -> np.ndarray: ...

    @abstractmethod
    def release(self) -> None: ...


class OpenCVCamera(CameraInterface):
    """Fallback USB/webcam implementation for development/testing."""

    def __init__(self, device_index: int = 0):
        self._cap = cv2.VideoCapture(device_index)
        if not self._cap.isOpened():
            self._cap.release()
            raise IOError(f"Cannot open camera at index {device_index}")

    def capture(self) -> np.ndarray:
        if self._cap is None:
            raise IOError("Camera has been released")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise IOError("Frame capture failed")
        return ensure_bgr(frame)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
