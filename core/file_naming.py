import re
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

import cv2

from core.image_utils import ensure_bgr, write_image

try:
    from pyzbar.pyzbar import decode as zbar_decode
    _HAS_PYZBAR = True
except Exception:  # ImportError, or OSError/FileNotFoundError when the native zbar library is missing
    _HAS_PYZBAR = False

try:
    import pytesseract
    _HAS_PYTESSERACT_MODULE = True
except Exception:
    _HAS_PYTESSERACT_MODULE = False

# Lazy singleton — EasyOCR model load is expensive, load once. The lock
# stops two inspection threads from loading the model at the same time.
_easyocr_reader = None
_easyocr_failed = False
_easyocr_lock = threading.Lock()


def _get_easyocr_reader():
    global _easyocr_reader, _easyocr_failed
    with _easyocr_lock:
        if _easyocr_reader is None and not _easyocr_failed:
            try:
                import easyocr
                _easyocr_reader = easyocr.Reader(["en"], gpu=_cuda_available())
            except Exception as exc:
                # Don't retry (and re-pay the import cost) on every frame.
                _easyocr_failed = True
                print(f"[CodeScanner] EasyOCR unavailable: {exc}")
        return _easyocr_reader


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


@dataclass
class CodeReadResult:
    """What was actually decoded from a region, and by which method —
    used both to label the live overlay (QR/Barcode/OCR) and to build
    the saved filename."""
    text: Optional[str]
    detected_type: Optional[str]  # "QR", "Barcode", "OCR", or None if nothing was read


_NOTHING = CodeReadResult(text=None, detected_type=None)


class CodeScanner:
    """
    Reads QR codes, barcodes, or OCR serial numbers from marked Code
    Regions (or the whole frame if none are marked/enabled).

    OCR backend selection is automatic:
      - If a valid Tesseract executable path is configured -> uses pytesseract.
      - Otherwise -> transparently falls back to EasyOCR, so OCR works for
        any user even if they never install/configure Tesseract.

    A single scanner is shared by every inspection worker thread, so the
    (non-thread-safe) OpenCV QR detector and OCR engines are used under a lock.
    """

    def __init__(self, tesseract_path: Optional[str] = None):
        self._cv_qr_detector = cv2.QRCodeDetector()
        self._lock = threading.RLock()
        self.tesseract_path: Optional[str] = None
        self.set_tesseract_path(tesseract_path)

    def set_tesseract_path(self, tesseract_path: Optional[str]) -> None:
        with self._lock:
            self.tesseract_path = (tesseract_path or "").strip() or None
            if self.tesseract_ready():
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_path

    def tesseract_ready(self) -> bool:
        return bool(
            _HAS_PYTESSERACT_MODULE and self.tesseract_path and Path(self.tesseract_path).is_file()
        )

    @staticmethod
    def _gray(image):
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    def scan_qr_or_barcode(self, image) -> CodeReadResult:
        gray = self._gray(image)
        if _HAS_PYZBAR:
            try:
                # pyzbar only looks at the first channel of a 3-channel array
                # (i.e. blue), so hand it a proper grayscale image.
                results = zbar_decode(gray)
                if results:
                    raw = results[0]
                    text = raw.data.decode("utf-8", errors="ignore")
                    symbology = (raw.type or "").upper()
                    detected_type = "QR" if "QR" in symbology else "Barcode"
                    return CodeReadResult(text=text, detected_type=detected_type)
            except Exception:
                pass
        try:
            with self._lock:
                data, _points, _ = self._cv_qr_detector.detectAndDecode(image)
            if data:
                return CodeReadResult(text=data, detected_type="QR")
        except Exception:
            pass
        return _NOTHING

    def scan_ocr(self, image) -> CodeReadResult:
        text = None
        with self._lock:
            if self.tesseract_ready():
                try:
                    text = pytesseract.image_to_string(self._gray(image), config="--psm 7").strip() or None
                except Exception:
                    text = None
            if not text:
                reader = _get_easyocr_reader()
                if reader is not None:
                    try:
                        results = reader.readtext(image, detail=0)
                        text = " ".join(results).strip() or None
                    except Exception:
                        text = None
        return CodeReadResult(text=text, detected_type="OCR" if text else None)

    def scan_region(self, image, region) -> CodeReadResult:
        img_h, img_w = image.shape[:2]
        x0, y0 = max(int(region.x), 0), max(int(region.y), 0)
        x1, y1 = min(int(region.x + region.w), img_w), min(int(region.y + region.h), img_h)
        if x1 <= x0 or y1 <= y0:
            return _NOTHING
        crop = image[y0:y1, x0:x1]
        code_type = getattr(region, "code_type", "Auto")
        if code_type == "OCR":
            return self.scan_ocr(crop)
        if code_type in ("QR", "Barcode"):
            return self.scan_qr_or_barcode(crop)
        result = self.scan_qr_or_barcode(crop)
        if result.text:
            return result
        return self.scan_ocr(crop)

    def scan(self, image, code_regions: Optional[List] = None) -> CodeReadResult:
        image = ensure_bgr(image)
        if code_regions:
            for region in code_regions:
                if not getattr(region, "enabled", True):
                    continue
                result = self.scan_region(image, region)
                if result.text:
                    return result
            return _NOTHING
        return self.scan_qr_or_barcode(image)


class OutputFileNamer:
    """
    With an enabled Code Region successfully read:
        [Code]_[YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg
    Without one (or nothing decoded):
        [YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg
    If that name is already taken (two frames in the same millisecond),
    a _1, _2, ... suffix is added instead of overwriting the earlier image.
    """

    _SANITIZE_RE = re.compile(r"[^A-Za-z0-9_\-]")

    def __init__(self, pass_dir: str, fail_dir: str, scanner: Optional[CodeScanner] = None):
        self.pass_dir = Path(pass_dir)
        self.fail_dir = Path(fail_dir)
        self.pass_dir.mkdir(parents=True, exist_ok=True)
        self.fail_dir.mkdir(parents=True, exist_ok=True)
        self.scanner = scanner or CodeScanner()
        self._save_lock = threading.Lock()

    def _sanitize(self, code: str) -> str:
        return self._SANITIZE_RE.sub("", code)[:64]

    @staticmethod
    def _timestamp(now: Optional[datetime] = None) -> str:
        # One clock read: the old code read the clock twice, so the
        # millisecond part could belong to a different second.
        now = now or datetime.now()
        return now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond // 1000:03d}"

    def build_filename(self, image, passed: bool, code_regions: Optional[List] = None,
                       precomputed_code: Optional[str] = None) -> str:
        status = "Pass" if passed else "Fail"
        timestamp = self._timestamp()
        code_text = precomputed_code
        if code_text is None:
            image = ensure_bgr(image)
            result = self.scanner.scan(image, code_regions=code_regions)
            code_text = result.text
        code_text = self._sanitize(code_text) if code_text else ""
        if code_text:
            return f"{code_text}_{timestamp}_{status}.jpg"
        return f"{timestamp}_{status}.jpg"

    def save(self, image, passed: bool, code_regions: Optional[List] = None,
             precomputed_code: Optional[str] = None) -> Path:
        image = ensure_bgr(image)
        filename = self.build_filename(image, passed, code_regions=code_regions, precomputed_code=precomputed_code)
        target_dir = self.pass_dir if passed else self.fail_dir
        with self._save_lock:
            # Re-create the folder in case it was deleted while the app was running.
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = target_dir / filename
            stem, suffix = out_path.stem, out_path.suffix
            counter = 1
            while out_path.exists():
                out_path = target_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            write_image(out_path, image)
        return out_path
