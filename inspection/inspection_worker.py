from PySide6.QtCore import QRunnable, Signal, QObject, Slot
import numpy as np
from inspection.inspection_engine import InspectionEngine, InspectionResult
from core.file_naming import OutputFileNamer
from core.image_utils import ensure_bgr

class WorkerSignals(QObject):
    finished = Signal(object, object)  # InspectionResult, saved_path
    error = Signal(str)

class InspectionWorker(QRunnable):
    def __init__(self, engine: InspectionEngine, namer: OutputFileNamer, image: np.ndarray):
        super().__init__()
        self.engine = engine
        self.namer = namer
        self.image = image
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            self.image = ensure_bgr(self.image)
            result: InspectionResult = self.engine.inspect(self.image)

            # Reuse the engine's already-decoded Code Region results for
            # naming, instead of re-scanning — first enabled region with a
            # successful read wins.
            precomputed_code = None
            for cr in result.code_region_results:
                if cr.enabled and cr.decoded_text:
                    precomputed_code = cr.decoded_text
                    break

            saved_path = self.namer.save(
                result.annotated_image, result.module_passed, precomputed_code=precomputed_code
            )
            self.signals.finished.emit(result, saved_path)
        except Exception as exc:
            self.signals.error.emit(str(exc))
