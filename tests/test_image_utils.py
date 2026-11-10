import cv2
import numpy as np
import pytest

from core.image_utils import ensure_bgr, bayer_to_bgr, read_image, write_image, _to_8bit


def test_none_passthrough():
    assert ensure_bgr(None) is None


def test_gray_2d_to_bgr():
    out = ensure_bgr(np.zeros((10, 12), np.uint8))
    assert out.shape == (10, 12, 3) and out.dtype == np.uint8


def test_single_channel_3d_to_bgr():
    assert ensure_bgr(np.zeros((10, 12, 1), np.uint8)).shape == (10, 12, 3)


def test_bgr_returned_as_is():
    img = np.zeros((4, 4, 3), np.uint8)
    assert ensure_bgr(img) is img


def test_bgra_drops_alpha():
    img = np.zeros((4, 4, 4), np.uint8)
    img[..., 2] = 200
    out = ensure_bgr(img)
    assert out.shape == (4, 4, 3) and out[0, 0, 2] == 200


def test_16bit_scaled_to_full_range():
    img = np.array([[0, 1000], [2000, 4000]], dtype=np.uint16)
    out = ensure_bgr(img)
    assert out.dtype == np.uint8
    assert out[..., 0].min() == 0 and out[..., 0].max() == 255


def test_constant_16bit_does_not_wrap():
    # Regression: 4000 cast straight to uint8 wrapped to 160.
    out = _to_8bit(np.full((3, 3), 4000, dtype=np.uint16))
    assert (out == 255).all()


def test_bad_channel_count_raises():
    with pytest.raises(ValueError):
        ensure_bgr(np.zeros((4, 4, 2), np.uint8))


def test_bayer_to_bgr_and_bad_pattern():
    raw = np.random.default_rng(0).integers(0, 255, (8, 8), dtype=np.uint8)
    assert bayer_to_bgr(raw, "RG").shape == (8, 8, 3)
    with pytest.raises(ValueError):
        bayer_to_bgr(raw, "XX")


def test_read_write_non_ascii_path(tmp_path):
    img = np.full((5, 6, 3), 77, np.uint8)
    path = tmp_path / "платa_é.png"
    write_image(path, img)
    back = read_image(path)
    assert back is not None and np.array_equal(back, img)


def test_read_missing_returns_none(tmp_path):
    assert read_image(tmp_path / "nope.png") is None


def test_write_to_missing_dir_raises(tmp_path):
    with pytest.raises(IOError):
        write_image(tmp_path / "no" / "such" / "dir.png", np.zeros((2, 2, 3), np.uint8))
