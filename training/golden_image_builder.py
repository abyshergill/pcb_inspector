import cv2
import numpy as np
from typing import List

class GoldenImageBuilder:
    """
    Ingests one or more reference PCB images, aligns them (ECC homography),
    and produces a noise-reduced 'Golden Image' baseline.

    Works with any number of images >= 1, but accuracy improves with more
    reference samples. RECOMMENDED_MIN_IMAGES is used only to show a
    non-blocking hint to the user — it does not prevent building.
    """

    RECOMMENDED_MIN_IMAGES = 5

    def __init__(self, image_paths: List[str]):
        if len(image_paths) < 1:
            raise ValueError("At least one reference image is required.")
        self.image_paths = image_paths

    def _align(self, ref_gray: np.ndarray, img_gray: np.ndarray) -> np.ndarray:
        warp_matrix = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
        try:
            _, warp_matrix = cv2.findTransformECC(
                ref_gray, img_gray, warp_matrix, cv2.MOTION_AFFINE, criteria
            )
        except cv2.error:
            pass  # fall back to unaligned frame if ECC fails to converge
        h, w = ref_gray.shape
        return cv2.warpAffine(img_gray, warp_matrix, (w, h),
                               flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP)

    def build(self) -> np.ndarray:
        """Returns a denoised, averaged BGR golden image."""
        images = [cv2.imread(p) for p in self.image_paths]
        if any(im is None for im in images):
            raise IOError("One or more reference images failed to load.")

        ref = images[0]
        ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
        accumulator = ref.astype(np.float32)

        for img in images[1:]:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            aligned_gray = self._align(ref_gray, gray)
            aligned_color = cv2.cvtColor(aligned_gray, cv2.COLOR_GRAY2BGR)
            accumulator += cv2.resize(aligned_color, (ref.shape[1], ref.shape[0])).astype(np.float32)

        averaged = (accumulator / len(images)).astype(np.uint8)
        golden = cv2.fastNlMeansDenoisingColored(averaged, None, 6, 6, 7, 21)
        return golden

    def save(self, output_path: str) -> str:
        golden = self.build()
        cv2.imwrite(output_path, golden)
        return output_path
