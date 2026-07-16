import csv
import time
from pathlib import Path
from typing import Optional

class InspectionLogger:
    """
    CSV-based inspection event logger. Call start() to begin logging to a
    timestamped file inside the configured logging directory; log() appends
    one row per component result while active; stop() closes the file.
    """

    def __init__(self, logging_dir: str):
        self.logging_dir = Path(logging_dir)
        self._file = None
        self._writer = None
        self.active = False
        self.current_log_path: Optional[Path] = None

    def set_logging_dir(self, logging_dir: str) -> None:
        self.logging_dir = Path(logging_dir)

    def start(self) -> Path:
        self.logging_dir.mkdir(parents=True, exist_ok=True)
        filename = f"inspection_log_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self.current_log_path = self.logging_dir / filename
        self._file = open(self.current_log_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow([
            "timestamp", "saved_filename", "module_similarity", "module_result",
            "component_name", "component_similarity", "component_result"
        ])
        self._file.flush()
        self.active = True
        return self.current_log_path

    def stop(self) -> None:
        if self._file:
            self._file.close()
        self._file = None
        self._writer = None
        self.active = False

    def log(self, result, saved_path) -> None:
        if not self.active or not self._writer:
            return
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        module_status = "PASS" if result.module_passed else "FAIL"
        saved_name = getattr(saved_path, "name", str(saved_path))
        rows = result.component_results or [None]
        for comp in rows:
            if comp:
                self._writer.writerow([
                    timestamp, saved_name, f"{result.module_similarity:.2f}", module_status,
                    comp.name, f"{comp.similarity:.2f}", "PASS" if comp.passed else "FAIL"
                ])
            else:
                self._writer.writerow([timestamp, saved_name, f"{result.module_similarity:.2f}", module_status, "", "", ""])
        self._file.flush()
