import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
from core.models import MasterTemplate
from core.file_naming import CodeScanner
from core.image_utils import ensure_bgr

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

        golden_bgr = cv2.imread(template.golden_image_path, cv2.IMREAD_UNCHANGED)
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
            gpu_mat = cv2.cuda_GpuMat()
            gpu_mat.upload(image)
            gpu_gray = cv2.cuda.cvtColor(gpu_mat, cv2.COLOR_BGR2GRAY)
            return gpu_gray.download()
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _region_similarity(self, golden_region: np.ndarray, test_region: np.ndarray) -> float:
        if golden_region.shape != test_region.shape:
            test_region = cv2.resize(test_region, (golden_region.shape[1], golden_region.shape[0]))
        result = cv2.matchTemplate(test_region.astype(np.float32), golden_region.astype(np.float32), cv2.TM_CCOEFF_NORMED)
        score = float(np.clip(result[0][0], -1.0, 1.0))
        return (score + 1.0) / 2.0 * 100.0

    def _draw_overlay(self, image: np.ndarray, comp, color, similarity: float) -> None:
        line_width = getattr(comp, "line_width", 2)
        font_scale = max(0.3, getattr(comp, "font_size", 10) / 20.0)
        if getattr(comp, "shape", "rect") == "circle":
            center = (comp.x + comp.w // 2, comp.y + comp.h // 2)
            axes = (comp.w // 2, comp.h // 2)
            cv2.ellipse(image, center, axes, 0, 0, 360, color, line_width)
        else:
            cv2.rectangle(image, (comp.x, comp.y), (comp.x + comp.w, comp.y + comp.h), color, line_width)
        cv2.putText(image, f"{comp.name}: {similarity:.1f}%", (comp.x, max(comp.y - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 1, cv2.LINE_AA)

    def _draw_code_region_overlay(self, image: np.ndarray, region, decoded_text: Optional[str],
                                   detected_type: Optional[str]) -> None:
        color = (0, 165, 255)  # orange (BGR)
        line_width = getattr(region, "line_width", 2)
        label_type = detected_type or region.code_type
        label = f"{label_type}: {decoded_text}" if decoded_text else f"{region.code_type}: Not Found"
        if getattr(region, "shape", "rect") == "circle":
            center = (region.x + region.w // 2, region.y + region.h // 2)
            axes = (region.w // 2, region.h // 2)
            cv2.ellipse(image, center, axes, 0, 0, 360, color, line_width)
        else:
            cv2.rectangle(image, (region.x, region.y), (region.x + region.w, region.y + region.h), color, line_width)
        cv2.putText(image, label, (region.x, max(region.y - 8, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    def inspect(self, image_bgr: np.ndarray) -> InspectionResult:
        if image_bgr.shape[:2] != self.golden_bgr.shape[:2]:
            image_bgr = cv2.resize(image_bgr, (self.golden_bgr.shape[1], self.golden_bgr.shape[0]))

        test_gray = self._to_gray(image_bgr)
        annotated = image_bgr.copy()
        mono_annotated = cv2.cvtColor(test_gray, cv2.COLOR_GRAY2BGR)

        component_results: List[ComponentResult] = []
        for comp in self.template.components:
            golden_roi = self.golden_gray[comp.y:comp.y + comp.h, comp.x:comp.x + comp.w]
            test_roi = test_gray[comp.y:comp.y + comp.h, comp.x:comp.x + comp.w]
            similarity = self._region_similarity(golden_roi, test_roi) if golden_roi.size and test_roi.size else 0.0
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

        module_similarity = self._region_similarity(self.golden_gray, test_gray)
        module_passed = module_similarity >= self.template.module_similarity_threshold and all(c.passed for c in component_results)

        return InspectionResult(module_similarity, module_passed, component_results, code_region_results, annotated, mono_annotated)
