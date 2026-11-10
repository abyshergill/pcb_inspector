import cv2
import numpy as np
from typing import List

from core.image_utils import ensure_bgr, read_image, write_image


class GoldenImageBuilder:
    """
    Ingests one or more reference PCB images, aligns them (ECC affine),
    and produces a noise-reduced 'Golden Image' baseline.

    Works with any number of images >= 1, but accuracy improves with more
    reference samples. RECOMMENDED_MIN_IMAGES is used only to show a
    non-blocking hint to the user — it does not prevent building.
    """

    RECOMMENDED_MIN_IMAGES = 5

    def __init__(self, image_paths: List[str]):
        if len(image_paths) < 1:
            raise ValueError("At least one reference image is required.")
        self.image_paths = list(image_paths)

    @staticmethod
    def _estimate_warp(ref_gray: np.ndarray, img_gray: np.ndarray) -> np.ndarray:
        warp_matrix = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
        try:
            # inputMask/gaussFiltSize passed explicitly: some OpenCV 4.x Python
            # builds reject the 5-argument form.
            _, warp_matrix = cv2.findTransformECC(
                ref_gray, img_gray, warp_matrix, cv2.MOTION_AFFINE, criteria, None, 5
            )
        except cv2.error:
            warp_matrix = np.eye(2, 3, dtype=np.float32)  # ECC failed to converge: use unaligned frame
        return warp_matrix

    def _align(self, ref_gray: np.ndarray, img_bgr: np.ndarray) -> np.ndarray:
        """Aligns a full-colour frame to the reference. (The old code aligned
        only the grayscale copy and averaged that into the colour reference,
        which washed the colours out of the golden image.)"""
        h, w = ref_gray.shape
        if img_bgr.shape[:2] != (h, w):
            img_bgr = cv2.resize(img_bgr, (w, h))
        img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        warp_matrix = self._estimate_warp(ref_gray, img_gray)
        return cv2.warpAffine(img_bgr, warp_matrix, (w, h),
                              flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_REPLICATE)

    def load_images(self) -> List[np.ndarray]:
        images = [read_image(p, cv2.IMREAD_UNCHANGED) for p in self.image_paths]
        failed = [p for p, im in zip(self.image_paths, images) if im is None]
        if failed:
            raise IOError("These reference images failed to load:\n" + "\n".join(failed))
        return [ensure_bgr(im) for im in images]

    def build(self) -> np.ndarray:
        """Returns a denoised, averaged BGR golden image."""
        images = self.load_images()

        ref = images[0]
        ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
        accumulator = ref.astype(np.float32)

        for img in images[1:]:
            accumulator += self._align(ref_gray, img).astype(np.float32)

        averaged = np.clip(np.rint(accumulator / len(images)), 0, 255).astype(np.uint8)
        golden = cv2.fastNlMeansDenoisingColored(averaged, None, 6, 6, 7, 21)
        return golden

    def save(self, output_path: str) -> str:
        golden = self.build()
        write_image(output_path, golden)
        return output_path
