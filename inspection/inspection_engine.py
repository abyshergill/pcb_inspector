import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple
from core.models import MasterTemplate
from core.file_naming import CodeScanner
from core.image_utils import ensure_bgr, read_image

# Below this standard deviation a region is treated as flat (featureless),
# where normalized correlation is undefined (division by ~0).
_FLAT_STD = 1e-3


@dataclass
class ComponentResult:
    name: str
    x: int
    y: int
    w: int
    h: int
    similarity: float
    passed: bool


@dataclass
class CodeRegionResult:
    """What was actually read from a Code Region during this inspection —
    shown live on the overlay and in the results list."""
    region_id: str
    configured_type: str
    x: int
    y: int
    w: int
    h: int
    decoded_text: Optional[str]
    detected_type: Optional[str]
    enabled: bool


@dataclass
class InspectionResult:
    module_similarity: float
    module_passed: bool
    component_results: List[ComponentResult]
    code_region_results: List[CodeRegionResult]
    annotated_image: np.ndarray
    monochrome_image: np.ndarray


def clip_roi(x: int, y: int, w: int, h: int, shape) -> Optional[Tuple[slice, slice]]:
    """Clamps a box to the image bounds. Returns None if nothing is left.
    Plain slicing with a negative start (a box drawn partly outside the
    image) would wrap around and compare the wrong pixels."""
    img_h, img_w = shape[:2]
    x0, y0 = max(int(x), 0), max(int(y), 0)
    x1, y1 = min(int(x + w), img_w), min(int(y + h), img_h)
    if x1 <= x0 or y1 <= y0:
        return None
    return slice(y0, y1), slice(x0, x1)


class InspectionEngine:
    """
    Converts to grayscale internally for speed, uses CUDA when available,
    computes per-component + module-level similarity, and reads any
    marked Code Regions (QR/Barcode/OCR) so their decoded value and
    detected type can be shown live on both the color and monochrome views.
    """

    def __init__(self, template: MasterTemplate, code_scanner: Optional[CodeScanner] = None):
        self.template = template
        self.use_cuda = self._detect_cuda()
        self.code_scanner = code_scanner or CodeScanner()

        golden_bgr = read_image(template.golden_image_path, cv2.IMREAD_UNCHANGED)
        if golden_bgr is None:
            raise IOError(f"Cannot load golden image at {template.golden_image_path}")
        self.golden_bgr = ensure_bgr(golden_bgr)
        self.golden_gray = cv2.cvtColor(self.golden_bgr, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def _detect_cuda() -> bool:
        try:
            return cv2.cuda.getCudaEnabledDeviceCount() > 0
        except Exception:
            return False

    def _to_gray(self, image: np.ndarray) -> np.ndarray:
        if self.use_cuda:
            try:
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(image)
                gpu_gray = cv2.cuda.cvtColor(gpu_mat, cv2.COLOR_BGR2GRAY)
                return gpu_gray.download()
            except cv2.error:
                self.use_cuda = False  # GPU path broken at runtime: fall back permanently
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    @staticmethod
    def region_similarity(golden_region: np.ndarray, test_region: np.ndarray) -> float:
        """Similarity in percent (0-100). Normalized cross-correlation mapped
        from [-1, 1] to [0, 100]; flat regions fall back to an intensity
        comparison, because correlation is undefined there (it used to
        produce NaN, which always failed)."""
        if golden_region.size == 0 or test_region.size == 0:
            return 0.0
        if golden_region.shape != test_region.shape:
            test_region = cv2.resize(test_region, (golden_region.shape[1], golden_region.shape[0]))
        g = golden_region.astype(np.float32)
        t = test_region.astype(np.float32)
        if g.std() < _FLAT_STD or t.std() < _FLAT_STD:
            mean_abs_diff = float(np.mean(np.abs(g - t)))
            return float(np.clip(100.0 - mean_abs_diff / 255.0 * 100.0, 0.0, 100.0))
        result = cv2.matchTemplate(t, g, cv2.TM_CCOEFF_NORMED)
        score = float(result[0][0])
        if not np.isfinite(score):
            return 0.0
        score = float(np.clip(score, -1.0, 1.0))
        return (score + 1.0) / 2.0 * 100.0

    # Kept for backwards compatibility with any external callers.
    _region_similarity = region_similarity

    @staticmethod
    def _label_origin(x: int, y: int, h: int, font_scale: float) -> Tuple[int, int]:
        """Text above the box, or just inside it when the box touches the
        top edge (text at y=0 would be drawn off-image)."""
        text_h = int(22 * font_scale) + 2
        ty = y - 8
        if ty < text_h:
            ty = y + text_h
        return max(x, 0), ty

    def _draw_overlay(self, image: np.ndarray, comp, color, similarity: float) -> None:
        line_width = getattr(comp, "line_width", 2)
        font_scale = max(0.3, getattr(comp, "font_size", 10) / 20.0)
        if getattr(comp, "shape", "rect") == "circle":
            center = (comp.x + comp.w // 2, comp.y + comp.h // 2)
            axes = (max(comp.w // 2, 1), max(comp.h // 2, 1))
            cv2.ellipse(image, center, axes, 0, 0, 360, color, line_width)
        else:
            cv2.rectangle(image, (comp.x, comp.y), (comp.x + comp.w, comp.y + comp.h), color, line_width)
        cv2.putText(image, f"{comp.name}: {similarity:.1f}%", self._label_origin(comp.x, comp.y, comp.h, font_scale),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 1, cv2.LINE_AA)

    def _draw_code_region_overlay(self, image: np.ndarray, region, decoded_text: Optional[str],
                                  detected_type: Optional[str]) -> None:
        color = (0, 165, 255)  # orange (BGR)
        line_width = getattr(region, "line_width", 2)
        label_type = detected_type or region.code_type
        label = f"{label_type}: {decoded_text}" if decoded_text else f"{region.code_type}: Not Found"
        if getattr(region, "shape", "rect") == "circle":
            center = (region.x + region.w // 2, region.y + region.h // 2)
            axes = (max(region.w // 2, 1), max(region.h // 2, 1))
            cv2.ellipse(image, center, axes, 0, 0, 360, color, line_width)
        else:
            cv2.rectangle(image, (region.x, region.y), (region.x + region.w, region.y + region.h), color, line_width)
        cv2.putText(image, label, self._label_origin(region.x, region.y, region.h, 0.5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    def inspect(self, image_bgr: np.ndarray) -> InspectionResult:
        if image_bgr is None:
            raise ValueError("No image to inspect")
        image_bgr = ensure_bgr(image_bgr)
        if image_bgr.shape[:2] != self.golden_bgr.shape[:2]:
            image_bgr = cv2.resize(image_bgr, (self.golden_bgr.shape[1], self.golden_bgr.shape[0]))

        test_gray = self._to_gray(image_bgr)
        annotated = image_bgr.copy()
        mono_annotated = cv2.cvtColor(test_gray, cv2.COLOR_GRAY2BGR)

        component_results: List[ComponentResult] = []
        for comp in self.template.components:
            roi = clip_roi(comp.x, comp.y, comp.w, comp.h, self.golden_gray.shape)
            if roi is None:
                similarity = 0.0  # box lies completely outside the image
            else:
                similarity = self.region_similarity(self.golden_gray[roi], test_gray[roi])
            passed = similarity >= comp.similarity_threshold
            component_results.append(ComponentResult(comp.name, comp.x, comp.y, comp.w, comp.h, similarity, passed))

            color = (0, 200, 0) if passed else (0, 0, 255)
            self._draw_overlay(annotated, comp, color, similarity)
            self._draw_overlay(mono_annotated, comp, color, similarity)

        code_region_results: List[CodeRegionResult] = []
        for region in self.template.code_regions:
            read_result = self.code_scanner.scan_region(image_bgr, region)
            code_region_results.append(CodeRegionResult(
                region_id=region.region_id,
                configured_type=region.code_type,
                x=region.x, y=region.y, w=region.w, h=region.h,
                decoded_text=read_result.text,
                detected_type=read_result.detected_type,
                enabled=getattr(region, "enabled", True),
            ))
            self._draw_code_region_overlay(annotated, region, read_result.text, read_result.detected_type)
            self._draw_code_region_overlay(mono_annotated, region, read_result.text, read_result.detected_type)

        module_similarity = self.region_similarity(self.golden_gray, test_gray)
        module_passed = (module_similarity >= self.template.module_similarity_threshold
                         and all(c.passed for c in component_results))

        return InspectionResult(module_similarity, module_passed, component_results, code_region_results,
                                annotated, mono_annotated)
