import cv2
import numpy as np
import pytest

from core.models import MasterTemplate, ComponentAnnotation, CodeRegionAnnotation
from inspection.inspection_engine import InspectionEngine, clip_roi


def _engine(golden_path, components, module=90.0, regions=()):
    t = MasterTemplate("t", str(golden_path), module, list(components), list(regions))
    return InspectionEngine(t)


CHIP = ComponentAnnotation("U1", 15, 15, 80, 70, similarity_threshold=95.0)
CAP = ComponentAnnotation("C1", 170, 30, 60, 60, similarity_threshold=95.0, shape="circle")


def test_identical_image_passes(golden_path, pcb_image):
    res = _engine(golden_path, [CHIP, CAP]).inspect(pcb_image)
    assert res.module_passed
    assert res.module_similarity == pytest.approx(100.0, abs=0.01)
    assert all(c.passed for c in res.component_results)
    assert res.annotated_image.shape == pcb_image.shape
    assert res.monochrome_image.shape == pcb_image.shape


def test_missing_component_fails(golden_path, pcb_image):
    bad = pcb_image.copy()
    cv2.circle(bad, (200, 60), 30, (30, 90, 20), -1)  # capacitor removed
    res = _engine(golden_path, [CHIP, CAP]).inspect(bad)
    results = {c.name: c for c in res.component_results}
    assert results["U1"].passed
    assert not results["C1"].passed
    assert not res.module_passed  # one failed component fails the board


def test_overlay_colours(golden_path, pcb_image):
    bad = pcb_image.copy()
    cv2.circle(bad, (200, 60), 30, (30, 90, 20), -1)
    res = _engine(golden_path, [CHIP, CAP]).inspect(bad)
    # green box edge for passing U1, red ellipse for failing C1
    assert tuple(res.annotated_image[15, 50]) == (0, 200, 0)
    assert tuple(res.annotated_image[60, 170]) == (0, 0, 255)


def test_different_size_frame_is_resized(golden_path, pcb_image):
    big = cv2.resize(pcb_image, (640, 480))
    res = _engine(golden_path, [CHIP]).inspect(big)
    assert res.annotated_image.shape[:2] == pcb_image.shape[:2]
    assert res.module_passed


def test_gray_and_bgra_frames_accepted(golden_path, pcb_image):
    eng = _engine(golden_path, [CHIP], module=0.0)
    eng.inspect(cv2.cvtColor(pcb_image, cv2.COLOR_BGR2GRAY))
    eng.inspect(cv2.cvtColor(pcb_image, cv2.COLOR_BGR2BGRA))


def test_out_of_bounds_component_scores_zero(golden_path, pcb_image):
    outside = ComponentAnnotation("X", 1000, 1000, 10, 10)
    res = _engine(golden_path, [outside]).inspect(pcb_image)
    assert res.component_results[0].similarity == 0.0
    assert not res.component_results[0].passed


def test_negative_origin_is_clipped_not_wrapped(golden_path, pcb_image):
    # Regression: a box starting at negative coords sliced from the far edge.
    partial = ComponentAnnotation("P", -20, -20, 100, 100, similarity_threshold=99.0)
    res = _engine(golden_path, [partial]).inspect(pcb_image)
    assert res.component_results[0].passed


def test_flat_regions_are_not_nan():
    flat = np.full((20, 20), 100, np.uint8)
    assert InspectionEngine.region_similarity(flat, flat) == pytest.approx(100.0)
    other = np.full((20, 20), 200, np.uint8)
    s = InspectionEngine.region_similarity(flat, other)
    assert np.isfinite(s) and s < 70
    textured = np.random.default_rng(1).integers(0, 255, (20, 20), dtype=np.uint8)
    assert np.isfinite(InspectionEngine.region_similarity(flat, textured))


def test_clip_roi():
    assert clip_roi(-5, -5, 10, 10, (100, 100)) == (slice(0, 5), slice(0, 5))
    assert clip_roi(95, 95, 10, 10, (100, 100)) == (slice(95, 100), slice(95, 100))
    assert clip_roi(200, 0, 10, 10, (100, 100)) is None


def test_missing_golden_raises(tmp_path):
    with pytest.raises(IOError):
        InspectionEngine(MasterTemplate("t", str(tmp_path / "missing.png")))


def test_code_region_results_reported(golden_path, pcb_image):
    region = CodeRegionAnnotation("QR", 10, 10, 50, 50, enabled=False)
    res = _engine(golden_path, [CHIP], regions=[region]).inspect(pcb_image)
    cr = res.code_region_results[0]
    assert cr.decoded_text is None and cr.enabled is False and cr.configured_type == "QR"


def test_none_image_raises(golden_path):
    with pytest.raises(ValueError):
        _engine(golden_path, [CHIP]).inspect(None)
