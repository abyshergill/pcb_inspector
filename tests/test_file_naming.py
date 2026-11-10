import re

import cv2
import numpy as np
import pytest

from core.file_naming import OutputFileNamer, CodeScanner, CodeReadResult
from core.models import CodeRegionAnnotation

TS = r"\d{8}_\d{6}_\d{3}"


def _qr_image(text="SN-00231"):
    enc = getattr(cv2, "QRCodeEncoder", None)
    if enc is None:
        pytest.skip("cv2.QRCodeEncoder not available in this OpenCV build")
    qr = enc.create().encode(text)
    qr = cv2.resize(qr, (qr.shape[1] * 8, qr.shape[0] * 8), interpolation=cv2.INTER_NEAREST)
    qr = cv2.copyMakeBorder(qr, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(qr, cv2.COLOR_GRAY2BGR)


@pytest.fixture
def namer(tmp_path):
    return OutputFileNamer(str(tmp_path / "pass"), str(tmp_path / "fail"))


def test_timestamp_format():
    assert re.fullmatch(TS, OutputFileNamer._timestamp())


def test_filename_with_code(namer):
    name = namer.build_filename(None, True, precomputed_code="SN 12/34")
    assert re.fullmatch(rf"SN1234_{TS}_Pass\.jpg", name)


def test_filename_without_code(namer):
    name = namer.build_filename(None, False, precomputed_code="")
    assert re.fullmatch(rf"{TS}_Fail\.jpg", name)


def test_code_that_sanitizes_to_empty_falls_back(namer):
    name = namer.build_filename(None, True, precomputed_code="///")
    assert re.fullmatch(rf"{TS}_Pass\.jpg", name)


def test_save_routes_and_never_overwrites(namer, tmp_path, monkeypatch):
    monkeypatch.setattr(OutputFileNamer, "_timestamp", staticmethod(lambda now=None: "20260101_000000_000"))
    img = np.zeros((10, 10, 3), np.uint8)
    p1 = namer.save(img, True, precomputed_code="")
    p2 = namer.save(img, True, precomputed_code="")
    p3 = namer.save(img, False, precomputed_code="")
    assert p1 != p2 and p1.exists() and p2.exists()
    assert p1.parent == tmp_path / "pass" and p3.parent == tmp_path / "fail"


def test_save_recreates_deleted_folder(namer, tmp_path):
    (tmp_path / "pass").rmdir()
    assert namer.save(np.zeros((4, 4), np.uint8), True, precomputed_code="").exists()


def test_scan_region_out_of_bounds_returns_nothing():
    scanner = CodeScanner()
    img = np.zeros((50, 50, 3), np.uint8)
    region = CodeRegionAnnotation("QR", 100, 100, 10, 10)
    assert scanner.scan_region(img, region) == CodeReadResult(None, None)


def test_scan_region_negative_coords_do_not_wrap(monkeypatch):
    scanner = CodeScanner()
    seen = {}
    monkeypatch.setattr(scanner, "scan_qr_or_barcode", lambda crop: seen.setdefault("shape", crop.shape) and CodeReadResult(None, None))
    scanner.scan_region(np.zeros((50, 60, 3), np.uint8), CodeRegionAnnotation("QR", -10, -5, 30, 20))
    assert seen["shape"][:2] == (15, 20)


def test_qr_decoded_from_region():
    img = _qr_image("SN-00231")
    scanner = CodeScanner()
    h, w = img.shape[:2]
    res = scanner.scan_region(img, CodeRegionAnnotation("QR", 0, 0, w, h))
    assert res.text == "SN-00231" and res.detected_type == "QR"


def test_disabled_regions_are_skipped():
    img = _qr_image()
    h, w = img.shape[:2]
    res = CodeScanner().scan(img, [CodeRegionAnnotation("QR", 0, 0, w, h, enabled=False)])
    assert res.text is None


def test_tesseract_path_validation(tmp_path):
    s = CodeScanner(tesseract_path=str(tmp_path / "missing.exe"))
    assert not s.tesseract_ready()
    s.set_tesseract_path("   ")
    assert s.tesseract_path is None
