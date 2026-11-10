import csv
import threading
import time
from pathlib import Path
from typing import Optional


class InspectionLogger:
    """
    CSV-based inspection event logger. Call start() to begin logging to a
    timestamped file inside the configured logging directory; log() appends
    one row per component result while active; stop() closes the file.
    """

    HEADER = [
        "timestamp", "saved_filename", "module_similarity", "module_result",
        "component_name", "component_similarity", "component_result"
    ]

    def __init__(self, logging_dir: str):
        self.logging_dir = Path(logging_dir)
        self._file = None
        self._writer = None
        self._lock = threading.Lock()
        self.active = False
        self.current_log_path: Optional[Path] = None

    def set_logging_dir(self, logging_dir: str) -> None:
        self.logging_dir = Path(logging_dir)

    def start(self) -> Path:
        # Starting twice used to leak the previous open file handle.
        if self.active:
            self.stop()
        self.logging_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        path = self.logging_dir / f"inspection_log_{stamp}.csv"
        counter = 1
        while path.exists():  # never truncate a log started in the same second
            path = self.logging_dir / f"inspection_log_{stamp}_{counter}.csv"
            counter += 1
        with self._lock:
            self.current_log_path = path
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(self.HEADER)
            self._file.flush()
            self.active = True
        return path

    def stop(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
            self._file = None
            self._writer = None
            self.active = False

    def log(self, result, saved_path) -> None:
        with self._lock:
            if not self.active or not self._writer:
                return
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            module_status = "PASS" if result.module_passed else "FAIL"
            saved_name = getattr(saved_path, "name", str(saved_path or ""))
            module_sim = f"{result.module_similarity:.2f}"
            if result.component_results:
                for comp in result.component_results:
                    self._writer.writerow([
                        timestamp, saved_name, module_sim, module_status,
                        comp.name, f"{comp.similarity:.2f}", "PASS" if comp.passed else "FAIL"
                    ])
            else:
                self._writer.writerow([timestamp, saved_name, module_sim, module_status, "", "", ""])
            self._file.flush()
