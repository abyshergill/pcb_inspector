import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
import cv2
from core.image_utils import ensure_bgr

try:
    from pyzbar.pyzbar import decode as zbar_decode
    _HAS_PYZBAR = True
except ImportError:
    _HAS_PYZBAR = False

try:
    import pytesseract
    _HAS_PYTESSERACT_MODULE = True
except ImportError:
    _HAS_PYTESSERACT_MODULE = False

_easyocr_reader = None  # lazy singleton — EasyOCR model load is expensive, load once

def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=True)
    return _easyocr_reader

@dataclass
class CodeReadResult:
    """What was actually decoded from a region, and by which method —
    used both to label the live overlay (QR/Barcode/OCR) and to build
    the saved filename."""
    text: Optional[str]
    detected_type: Optional[str]  # "QR", "Barcode", "OCR", or None if nothing was read

class CodeScanner:
    """
    Reads QR codes, barcodes, or OCR serial numbers from marked Code
    Regions (or the whole frame if none are marked/enabled).

    OCR backend selection is automatic:
      - If a valid Tesseract executable path is configured -> uses pytesseract.
      - Otherwise -> transparently falls back to EasyOCR, so OCR works for
        any user even if they never install/configure Tesseract.
    """

    def __init__(self, tesseract_path: Optional[str] = None):
        self._cv_qr_detector = cv2.QRCodeDetector()
        self.tesseract_path: Optional[str] = None
        self.set_tesseract_path(tesseract_path)

    def set_tesseract_path(self, tesseract_path: Optional[str]) -> None:
        self.tesseract_path = tesseract_path or None
        if self.tesseract_ready() and _HAS_PYTESSERACT_MODULE:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path

    def tesseract_ready(self) -> bool:
        return bool(
            _HAS_PYTESSERACT_MODULE and self.tesseract_path and Path(self.tesseract_path).is_file()
        )

    def scan_qr_or_barcode(self, image) -> CodeReadResult:
        if _HAS_PYZBAR:
            try:
                results = zbar_decode(image)
                if results:
                    raw = results[0]
                    text = raw.data.decode("utf-8", errors="ignore")
                    symbology = (raw.type or "").upper()
                    detected_type = "QR" if "QR" in symbology else "Barcode"
                    return CodeReadResult(text=text, detected_type=detected_type)
            except Exception:
                pass
        try:
            data, points, _ = self._cv_qr_detector.detectAndDecode(image)
            if data:
                return CodeReadResult(text=data, detected_type="QR")
        except Exception:
            pass
        return CodeReadResult(text=None, detected_type=None)

    def scan_ocr(self, image) -> CodeReadResult:
        text = None
        if self.tesseract_ready():
            try:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
                text = pytesseract.image_to_string(gray, config="--psm 7").strip() or None
            except Exception:
                text = None
        if not text:
            try:
                reader = _get_easyocr_reader()
                results = reader.readtext(image, detail=0)
                text = " ".join(results).strip() or None
            except Exception:
                text = None
        return CodeReadResult(text=text, detected_type="OCR" if text else None)

    def scan_region(self, image, region) -> CodeReadResult:
        x, y, w, h = region.x, region.y, region.w, region.h
        crop = image[max(y, 0):y + h, max(x, 0):x + w]
        if crop.size == 0:
            return CodeReadResult(text=None, detected_type=None)
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
            return CodeReadResult(text=None, detected_type=None)
        return self.scan_qr_or_barcode(image)

class OutputFileNamer:
    """
    With an enabled Code Region successfully read:
        [Code]_[YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg
    Without one (or nothing decoded):
        [YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg
    """

    _SANITIZE_RE = re.compile(r"[^A-Za-z0-9_\-]")

    def __init__(self, pass_dir: str, fail_dir: str, scanner: Optional[CodeScanner] = None):
        self.pass_dir = Path(pass_dir)
        self.fail_dir = Path(fail_dir)
        self.pass_dir.mkdir(parents=True, exist_ok=True)
        self.fail_dir.mkdir(parents=True, exist_ok=True)
        self.scanner = scanner or CodeScanner()

    def _sanitize(self, code: str) -> str:
        return self._SANITIZE_RE.sub("", code)[:64]

    def _timestamp(self) -> str:
        return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"

    def build_filename(self, image, passed: bool, code_regions: Optional[List] = None,
                        precomputed_code: Optional[str] = None) -> str:
        status = "Pass" if passed else "Fail"
        timestamp = self._timestamp()
        code_text = precomputed_code
        if code_text is None:
            image = ensure_bgr(image)
            result = self.scanner.scan(image, code_regions=code_regions)
            code_text = result.text
        if code_text:
            return f"{self._sanitize(code_text)}_{timestamp}_{status}.jpg"
        return f"{timestamp}_{status}.jpg"

    def save(self, image, passed: bool, code_regions: Optional[List] = None,
             precomputed_code: Optional[str] = None) -> Path:
        image = ensure_bgr(image)
        filename = self.build_filename(image, passed, code_regions=code_regions, precomputed_code=precomputed_code)
        target_dir = self.pass_dir if passed else self.fail_dir
        out_path = target_dir / filename
        cv2.imwrite(str(out_path), image)
        return out_path
