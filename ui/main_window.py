import os
import time
import cv2
from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QIcon

from ui.training_widget import TrainingModuleWidget
from ui.inspection_widget import InspectionWidget
from ui.hardware_panel import HardwareSyncPanel
from ui.live_capture_widget import LiveCaptureWidget
from ui.output_paths_widget import OutputPathsWidget
from core.app_settings import AppSettings
from core.template_manager import MasterTemplateManager
from core.file_naming import OutputFileNamer, CodeScanner
from core.inspection_logger import InspectionLogger
from inspection.inspection_engine import InspectionEngine
from inspection.inspection_worker import InspectionWorker
from networking.outbound_trigger import OutboundTriggerController
from networking.inbound_listener import InboundListenerThread
from camera.camera_interface import OpenCVCamera
import config

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCB Inspector")
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.resize(1400, 900)

        self.settings = AppSettings()
        self.thread_pool = QThreadPool.globalInstance()
        self.template_manager = MasterTemplateManager()
        self.namer = OutputFileNamer(
            self.settings.pass_dir, self.settings.fail_dir,
            scanner=CodeScanner(tesseract_path=self.settings.tesseract_path)
        )
        self.inspection_logger = InspectionLogger(self.settings.logging_dir)
        self.engine = None
        self.camera = None
        self.outbound_ctrl = None
        self.inbound_thread = None

        self.training_widget = TrainingModuleWidget(self.settings)
        self.inspection_widget = InspectionWidget()
        self.live_capture_widget = LiveCaptureWidget()
        self.output_paths_widget = OutputPathsWidget(self.settings)
        self.hardware_panel = HardwareSyncPanel()

        tabs = QTabWidget()
        tabs.addTab(self.training_widget, "Training / Master Registration")
        tabs.addTab(self.inspection_widget, "Live Inspection")
        tabs.addTab(self.live_capture_widget, "Live Capture")
        tabs.addTab(self.output_paths_widget, "I/O Paths")
        tabs.addTab(self.hardware_panel, "Hardware Sync")
        self.setCentralWidget(tabs)

        # Hardware Sync tab (Mode 1 / Mode 2 / Batch Testing + self-tests)
        self.hardware_panel.startOutboundRequested.connect(self._start_outbound)
        self.hardware_panel.stopOutboundRequested.connect(self._stop_outbound)
        self.hardware_panel.testTriggerRequested.connect(self._send_test_trigger)
        self.hardware_panel.startInboundRequested.connect(self._start_inbound)
        self.hardware_panel.stopInboundRequested.connect(self._stop_inbound)
        self.hardware_panel.batchImageRequested.connect(self._run_batch_image)
        self.hardware_panel.batchFolderRequested.connect(self._run_batch_folder)

        # Live Capture tab (preview / manual / auto capture)
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._update_live_preview)
        self.auto_capture_timer = QTimer(self)
        self.auto_capture_timer.timeout.connect(self._on_manual_capture)

        self.live_capture_widget.livePreviewStartRequested.connect(self._start_live_preview)
        self.live_capture_widget.livePreviewStopRequested.connect(self._stop_live_preview)
        self.live_capture_widget.manualCaptureRequested.connect(self._on_manual_capture)
        self.live_capture_widget.autoCaptureStartRequested.connect(self._start_auto_capture)
        self.live_capture_widget.autoCaptureStopRequested.connect(self._stop_auto_capture)

        # Output Image Path tab (pass/fail dirs, golden image upload, logging path, tesseract path)
        self.output_paths_widget.outputPathsChanged.connect(self._on_output_paths_changed)
        self.output_paths_widget.goldenImageUploaded.connect(self.training_widget.load_uploaded_golden_image)
        self.output_paths_widget.loggingPathChanged.connect(self._on_logging_path_changed)
        self.output_paths_widget.tesseractPathChanged.connect(self._on_tesseract_path_changed)

        # Live Inspection tab (start/stop logging)
        self.inspection_widget.startLoggingRequested.connect(self._start_logging)
        self.inspection_widget.stopLoggingRequested.connect(self._stop_logging)

    def _ensure_engine(self) -> bool:
        if self.engine:
            return True
        names = self.template_manager.list_templates()
        if not names:
            QMessageBox.warning(self, "No Master Template", "Register a Master Template in the Training tab first.")
            return False
        self.engine = InspectionEngine(self.template_manager.load(names[0]), code_scanner=self.namer.scanner)
        return True

    def _ensure_camera(self) -> bool:
        if self.camera:
            return True
        try:
            self.camera = OpenCVCamera(config.CAMERA_DEVICE_INDEX)
            return True
        except IOError as exc:
            QMessageBox.critical(self, "Camera Error", str(exc))
            return False

    def _submit_inspection(self, image):
        if not self._ensure_engine():
            return
        worker = InspectionWorker(self.engine, self.namer, image)
        worker.signals.finished.connect(self._on_inspection_finished)
        worker.signals.error.connect(lambda msg: QMessageBox.critical(self, "Inspection Error", msg))
        self.thread_pool.start(worker)

    def _on_inspection_finished(self, result, saved_path):
        self.inspection_widget.display_result(result)
        if self.inspection_logger.active:
            self.inspection_logger.log(result, saved_path)

    # ---- Mode 1: Outbound ----
    def _start_outbound(self, cfg):
        self.outbound_ctrl = OutboundTriggerController(cfg["host"], cfg["port"], cfg["protocol"], cfg["interval_ms"])
        self.outbound_ctrl.triggerSent.connect(self._on_outbound_trigger_fired)
        self.outbound_ctrl.triggerSent.connect(self._update_outbound_status)
        self.outbound_ctrl.start()
        self.hardware_panel.out_status_label.setText("Status: Running")

    def _stop_outbound(self):
        if self.outbound_ctrl:
            self.outbound_ctrl.stop()
        self.hardware_panel.out_status_label.setText("Status: Stopped")

    def _update_outbound_status(self):
        self.hardware_panel.out_status_label.setText(f"Status: Last trigger sent at {time.strftime('%H:%M:%S')}")

    def _send_test_trigger(self, cfg):
        try:
            temp_ctrl = OutboundTriggerController(cfg["host"], cfg["port"], cfg["protocol"], cfg["interval_ms"])
            temp_ctrl.send_once()
            self.hardware_panel.out_status_label.setText(f"Status: Test trigger sent at {time.strftime('%H:%M:%S')}")
        except OSError as exc:
            QMessageBox.critical(self, "Test Trigger Failed", str(exc))

    def _on_outbound_trigger_fired(self):
        if self._ensure_camera():
            try:
                self._submit_inspection(self.camera.capture())
            except IOError as exc:
                print(f"[MainWindow] capture failed: {exc}")

    # ---- Mode 2: Inbound ----
    def _start_inbound(self, cfg):
        self.inbound_thread = InboundListenerThread(cfg["host"], cfg["port"], cfg["protocol"])
        self.inbound_thread.triggerReceived.connect(self._on_inbound_trigger_received)
        self.inbound_thread.triggerReceived.connect(self._update_inbound_status)
        self.inbound_thread.listenerError.connect(self._on_inbound_error)
        self.inbound_thread.start()
        self.hardware_panel.in_status_label.setText("Status: Listening...")

    def _stop_inbound(self):
        if self.inbound_thread:
            self.inbound_thread.stop()
        self.hardware_panel.in_status_label.setText("Status: Not Listening")

    def _update_inbound_status(self, data: bytes):
        self.hardware_panel.in_status_label.setText(f"Status: Signal received at {time.strftime('%H:%M:%S')}")

    def _on_inbound_error(self, msg: str):
        QMessageBox.critical(self, "Listener Error", msg)
        self.hardware_panel.in_status_label.setText(f"Status: Error - {msg}")

    def _on_inbound_trigger_received(self, data: bytes):
        if self._ensure_camera():
            try:
                self._submit_inspection(self.camera.capture())
            except IOError as exc:
                print(f"[MainWindow] capture failed: {exc}")

    # ---- Batch Testing ----
    def _run_batch_image(self, path: str):
        image = cv2.imread(path)
        if image is None:
            QMessageBox.warning(self, "Invalid Image", f"Could not read {path}")
            return
        self._submit_inspection(image)

    def _run_batch_folder(self, folder: str):
        valid_ext = (".png", ".jpg", ".jpeg", ".bmp")
        for fname in sorted(os.listdir(folder)):
            if fname.lower().endswith(valid_ext):
                image = cv2.imread(os.path.join(folder, fname))
                if image is not None:
                    self._submit_inspection(image)

    # ---- Live Preview ----
    def _start_live_preview(self):
        if self._ensure_camera():
            self.preview_timer.start(config.LIVE_PREVIEW_INTERVAL_MS)

    def _stop_live_preview(self):
        self.preview_timer.stop()

    def _update_live_preview(self):
        if not self.camera:
            return
        try:
            frame = self.camera.capture()
            self.live_capture_widget.set_preview_frame(frame)
        except IOError as exc:
            print(f"[MainWindow] preview capture failed: {exc}")

    # ---- Manual Capture ----
    def _on_manual_capture(self):
        if self._ensure_camera():
            try:
                self._submit_inspection(self.camera.capture())
            except IOError as exc:
                print(f"[MainWindow] manual capture failed: {exc}")

    # ---- Auto Capture ----
    def _start_auto_capture(self, interval_ms: int):
        if self._ensure_camera():
            self.auto_capture_timer.start(interval_ms)

    def _stop_auto_capture(self):
        self.auto_capture_timer.stop()

    # ---- Output Paths ----
    def _on_output_paths_changed(self, pass_dir: str, fail_dir: str):
        self.namer = OutputFileNamer(pass_dir, fail_dir, scanner=self.namer.scanner)
        QMessageBox.information(self, "Output Paths Updated", f"Pass folder: {pass_dir}\nFail folder: {fail_dir}")

    def _on_logging_path_changed(self, log_dir: str):
        if self.inspection_logger.active:
            QMessageBox.warning(self, "Logging Active", "Stop logging before changing the logging path.")
            return
        self.inspection_logger.set_logging_dir(log_dir)

    def _on_tesseract_path_changed(self, path: str):
        self.namer.scanner.set_tesseract_path(path)

    # ---- Logging ----
    def _start_logging(self):
        log_path = self.inspection_logger.start()
        self.inspection_widget.set_logging_status(True, str(log_path))

    def _stop_logging(self):
        self.inspection_logger.stop()
        self.inspection_widget.set_logging_status(False)

    def closeEvent(self, event):
        self._stop_outbound()
        self._stop_inbound()
        self.preview_timer.stop()
        self.auto_capture_timer.stop()
        if self.inspection_logger.active:
            self.inspection_logger.stop()
        if self.camera:
            self.camera.release()
        event.accept()
