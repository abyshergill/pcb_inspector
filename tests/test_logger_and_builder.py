import csv

import cv2
import numpy as np
import pytest

from core.inspection_logger import InspectionLogger
from inspection.inspection_engine import InspectionResult, ComponentResult
from training.golden_image_builder import GoldenImageBuilder
from tests.conftest import make_pcb_image


def _result(components):
    img = np.zeros((2, 2, 3), np.uint8)
    return InspectionResult(93.456, True, components, [], img, img)


def test_logger_rows(tmp_path):
    log = InspectionLogger(str(tmp_path / "logs"))
    path = log.start()
    log.log(_result([ComponentResult("U1", 0, 0, 1, 1, 97.0, True),
                     ComponentResult("C1", 0, 0, 1, 1, 50.0, False)]), tmp_path / "a.jpg")
    log.log(_result([]), None)
    log.stop()
    rows = list(csv.reader(open(path, encoding="utf-8")))
    assert rows[0] == InspectionLogger.HEADER
    assert rows[1][1:] == ["a.jpg", "93.46", "PASS", "U1", "97.00", "PASS"]
    assert rows[2][4:] == ["C1", "50.00", "FAIL"]
    assert rows[3][4:] == ["", "", ""]


def test_logger_inactive_does_nothing(tmp_path):
    log = InspectionLogger(str(tmp_path))
    log.log(_result([]), "x")  # must not raise
    assert not list(tmp_path.glob("*.csv"))


def test_logger_double_start_does_not_truncate(tmp_path):
    log = InspectionLogger(str(tmp_path))
    first = log.start()
    log.log(_result([]), "a.jpg")
    second = log.start()
    log.stop()
    assert first != second
    assert len(list(csv.reader(open(first)))) == 2


def test_builder_keeps_colour(tmp_path):
    # Regression: aligned frames were averaged in as grayscale.
    paths = []
    for i in range(3):
        p = tmp_path / f"ref{i}.png"
        cv2.imwrite(str(p), make_pcb_image(seed=i))
        paths.append(str(p))
    golden = GoldenImageBuilder(paths).build()
    ref = make_pcb_image(seed=0)
    # Orange capacitor pixel must still be orange, not gray.
    b, g, r = (int(v) for v in golden[60, 185])
    assert r > 200 and b < 60, (b, g, r)
    assert golden.shape == ref.shape


def test_builder_aligns_shifted_frame(tmp_path):
    base = make_pcb_image(seed=0)
    shifted = cv2.warpAffine(base, np.float32([[1, 0, 4], [0, 1, 3]]), (base.shape[1], base.shape[0]),
                             borderMode=cv2.BORDER_REPLICATE)
    for name, img in (("a.png", base), ("b.png", shifted)):
        cv2.imwrite(str(tmp_path / name), img)
    golden = GoldenImageBuilder([str(tmp_path / "a.png"), str(tmp_path / "b.png")]).build()
    unaligned = ((base.astype(np.float32) + shifted) / 2).astype(np.uint8)
    err_aligned = np.abs(golden.astype(int) - base).mean()
    err_unaligned = np.abs(unaligned.astype(int) - base).mean()
    assert err_aligned < err_unaligned


def test_builder_different_sizes(tmp_path):
    cv2.imwrite(str(tmp_path / "a.png"), make_pcb_image())
    cv2.imwrite(str(tmp_path / "b.png"), cv2.resize(make_pcb_image(), (400, 300)))
    out = GoldenImageBuilder([str(tmp_path / "a.png"), str(tmp_path / "b.png")]).build()
    assert out.shape == (240, 320, 3)


def test_builder_errors(tmp_path):
    with pytest.raises(ValueError):
        GoldenImageBuilder([])
    with pytest.raises(IOError):
        GoldenImageBuilder([str(tmp_path / "missing.png")]).build()


def test_builder_save(tmp_path):
    cv2.imwrite(str(tmp_path / "a.png"), make_pcb_image())
    out = tmp_path / "golden.png"
    GoldenImageBuilder([str(tmp_path / "a.png")]).save(str(out))
    assert cv2.imread(str(out)) is not None
