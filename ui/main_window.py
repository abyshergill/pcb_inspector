import os
import time
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
from core.image_utils import read_image
from inspection.inspection_engine import InspectionEngine
from inspection.inspection_worker import InspectionWorker
from networking.outbound_trigger import OutboundTriggerController
from networking.inbound_listener import InboundListenerThread
from camera.camera_interface import OpenCVCamera
import config

BATCH_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


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
        self.active_template_name = None
        self.camera = None
        self.outbound_ctrl = None
        self.inbound_thread = None
        self._retired_threads = []
        self._pending_inspections = 0
        self._dropped_triggers = 0
        self._last_error_box_at = 0.0

        self.training_widget = TrainingModuleWidget(self.settings, template_manager=self.template_manager)
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
        self.auto_capture_timer.timeout.connect(self._on_auto_capture_tick)

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

        # Training -> Inspection: use a template as soon as it is saved
        self.training_widget.templateSaved.connect(self._on_template_saved)

        # Live Inspection tab (template selection, start/stop logging)
        self.inspection_widget.startLoggingRequested.connect(self._start_logging)
        self.inspection_widget.stopLoggingRequested.connect(self._stop_logging)
        self.inspection_widget.templateSelected.connect(self._select_template)
        self.inspection_widget.refreshTemplatesRequested.connect(self._refresh_template_list)
        self._refresh_template_list()

    # ---- template / engine ----
    def _refresh_template_list(self):
        names = self.template_manager.list_templates()
        self.inspection_widget.set_templates(names, self.active_template_name or (names[0] if names else None))

    def _select_template(self, name: str) -> bool:
        """Builds the inspection engine for the given template."""
        if not name:
            return False
        try:
            template = self.template_manager.load(name)
            self.engine = InspectionEngine(template, code_scanner=self.namer.scanner)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.engine = None
            self.active_template_name = None
            QMessageBox.critical(self, "Template Error", f"Could not load Master Template '{name}':\n{exc}")
            return False
        self.active_template_name = name
        self._refresh_template_list()
        return True

    def _on_template_saved(self, name: str):
        # The engine used to be cached forever, so a re-trained template was
        # ignored until restart. Switch to the template that was just saved.
        self._select_template(name)

    def _ensure_engine(self) -> bool:
        if self.engine:
            return True
        name = self.inspection_widget.template_combo.currentText() or self.template_manager.latest_template()
        if not name:
            QMessageBox.warning(self, "No Master Template", "Register a Master Template in the Training tab first.")
            return False
        return self._select_template(name)

    def _ensure_camera(self) -> bool:
        if self.camera:
            return True
        try:
            self.camera = OpenCVCamera(config.CAMERA_DEVICE_INDEX)
            return True
        except IOError as exc:
            QMessageBox.critical(self, "Camera Error", str(exc))
            return False

    # ---- inspection pipeline ----
    def _submit_inspection(self, image) -> bool:
        if not self._ensure_engine():
            return False
        worker = InspectionWorker(self.engine, self.namer, image)
        worker.signals.finished.connect(self._on_inspection_finished)
        worker.signals.error.connect(self._on_inspection_error)
        worker.signals.done.connect(self._on_inspection_done)
        self._pending_inspections += 1
        self.thread_pool.start(worker)
        return True

    def _capture_and_inspect(self, live: bool = True) -> bool:
        """Grabs one camera frame and queues it for inspection. For live
        triggers the frame is dropped while too many inspections are still
        pending, instead of piling up unbounded work. Returns False if the
        pipeline cannot run at all (no template / no camera), so callers
        driven by a timer can stop instead of showing a dialog every tick."""
        if live and self._pending_inspections >= config.MAX_PENDING_LIVE_INSPECTIONS:
            self._dropped_triggers += 1
            self.statusBar().showMessage(
                f"Inspection busy — skipped {self._dropped_triggers} trigger(s) so far", 3000
            )
            return True
        if not self._ensure_engine() or not self._ensure_camera():
            return False
        try:
            frame = self.camera.capture()
        except IOError as exc:
            self.statusBar().showMessage(f"Capture failed: {exc}", 5000)
            return True
        return self._submit_inspection(frame)

    def _on_inspection_finished(self, result, saved_path):
        self.inspection_widget.display_result(result)
        self.statusBar().showMessage(f"Saved {saved_path}", 5000)
        if self.inspection_logger.active:
            try:
                self.inspection_logger.log(result, saved_path)
            except OSError as exc:
                self._show_error_throttled("Logging Error", str(exc))

    def _on_inspection_error(self, msg: str):
        self._show_error_throttled("Inspection Error", msg)

    def _on_inspection_done(self):
        self._pending_inspections = max(0, self._pending_inspections - 1)

    def _show_error_throttled(self, title: str, msg: str):
        """Shows at most one error dialog every few seconds; a burst of
        failing inspections (e.g. a folder batch) otherwise opens a stack of
        modal dialogs. Everything still goes to the status bar."""
        self.statusBar().showMessage(f"{title}: {msg}", 8000)
        now = time.monotonic()
        if now - self._last_error_box_at > 5.0:
            self._last_error_box_at = now
            QMessageBox.critical(self, title, msg)

    # ---- Mode 1: Outbound ----
    def _make_outbound(self, cfg) -> OutboundTriggerController:
        return OutboundTriggerController(cfg["host"], cfg["port"], cfg["protocol"], cfg["interval_ms"], parent=self)

    def _start_outbound(self, cfg):
        # Starting twice used to leave the first controller's timer running
        # (double triggers, leaked socket).
        self._stop_outbound()
        if not self._ensure_engine() or not self._ensure_camera():
            return
        ctrl = self._make_outbound(cfg)
        ctrl.triggerSent.connect(self._on_outbound_trigger_fired)
        ctrl.triggerSent.connect(self._update_outbound_status)
        ctrl.triggerFailed.connect(self._on_outbound_failed)
        try:
            ctrl.start()
        except OSError as exc:
            ctrl.deleteLater()
            QMessageBox.critical(self, "Outbound Trigger",
                                 f"Could not connect to {cfg['host']}:{cfg['port']} ({cfg['protocol']}):\n{exc}")
            self.hardware_panel.out_status_label.setText("Status: Connection failed")
            return
        self.outbound_ctrl = ctrl
        self.hardware_panel.out_status_label.setText("Status: Running")

    def _stop_outbound(self):
        if self.outbound_ctrl:
            self.outbound_ctrl.stop()
            self.outbound_ctrl.deleteLater()
            self.outbound_ctrl = None
            self.hardware_panel.out_status_label.setText("Status: Stopped")

    def _update_outbound_status(self):
        self.hardware_panel.out_status_label.setText(f"Status: Last trigger sent at {time.strftime('%H:%M:%S')}")

    def _on_outbound_failed(self, msg: str):
        self.hardware_panel.out_status_label.setText(f"Status: Send failed at {time.strftime('%H:%M:%S')} - {msg}")

    def _send_test_trigger(self, cfg):
        ctrl = self._make_outbound(cfg)
        try:
            ctrl.send_once()
            self.hardware_panel.out_status_label.setText(f"Status: Test trigger sent at {time.strftime('%H:%M:%S')}")
        except OSError as exc:
            # Previously errors were swallowed and "sent" was always reported.
            QMessageBox.critical(self, "Test Trigger Failed", str(exc))
            self.hardware_panel.out_status_label.setText("Status: Test trigger failed")
        finally:
            ctrl.stop()
            ctrl.deleteLater()

    def _on_outbound_trigger_fired(self):
        if not self._capture_and_inspect(live=True):
            self._stop_outbound()

    # ---- Mode 2: Inbound ----
    def _start_inbound(self, cfg):
        self._stop_inbound()
        thread = InboundListenerThread(cfg["host"], cfg["port"], cfg["protocol"])
        thread.triggerReceived.connect(self._on_inbound_trigger_received)
        thread.triggerReceived.connect(self._update_inbound_status)
        thread.listenerError.connect(self._on_inbound_error)
        thread.listening.connect(
            lambda: self.hardware_panel.in_status_label.setText(
                f"Status: Listening on {cfg['host'] or '0.0.0.0'}:{cfg['port']} ({cfg['protocol']})")
        )
        self.inbound_thread = thread
        self.hardware_panel.in_status_label.setText("Status: Starting listener...")
        thread.start()

    def _stop_inbound(self):
        if self.inbound_thread:
            thread = self.inbound_thread
            thread.stop()
            if thread.isRunning():
                # Keep a reference until it really exits: destroying a running
                # QThread aborts the whole application.
                self._retired_threads.append(thread)
                thread.finished.connect(lambda t=thread: self._retired_threads.remove(t))
            self.inbound_thread = None
            self.hardware_panel.in_status_label.setText("Status: Not Listening")

    def _update_inbound_status(self, data: bytes):
        self.hardware_panel.in_status_label.setText(f"Status: Signal received at {time.strftime('%H:%M:%S')}")

    def _on_inbound_error(self, msg: str):
        QMessageBox.critical(self, "Listener Error", msg)
        self.hardware_panel.in_status_label.setText(f"Status: Error - {msg}")

    def _on_inbound_trigger_received(self, data: bytes):
        if not self._capture_and_inspect(live=True):
            self._stop_inbound()

    # ---- Batch Testing ----
    def _run_batch_image(self, path: str):
        image = read_image(path)
        if image is None:
            QMessageBox.warning(self, "Invalid Image", f"Could not read {path}")
            return
        self._submit_inspection(image)

    def _run_batch_folder(self, folder: str):
        if not self._ensure_engine():
            return
        try:
            names = sorted(os.listdir(folder))
        except OSError as exc:
            QMessageBox.warning(self, "Invalid Folder", str(exc))
            return
        queued, unreadable = 0, []
        for fname in names:
            if not fname.lower().endswith(BATCH_IMAGE_EXTENSIONS):
                continue
            image = read_image(os.path.join(folder, fname))
            if image is None:
                unreadable.append(fname)
                continue
            if self._submit_inspection(image):
                queued += 1
        msg = f"Queued {queued} image(s) from {folder} for inspection."
        if unreadable:
            msg += f"\nSkipped {len(unreadable)} unreadable file(s): {', '.join(unreadable[:10])}"
        if queued == 0 and not unreadable:
            msg = f"No images ({', '.join(BATCH_IMAGE_EXTENSIONS)}) found in {folder}."
        QMessageBox.information(self, "Batch Testing", msg)

    # ---- Live Preview ----
    def _start_live_preview(self):
        if self._ensure_camera():
            self.preview_timer.start(config.LIVE_PREVIEW_INTERVAL_MS)
            self.live_capture_widget.set_preview_running(True)

    def _stop_live_preview(self):
        self.preview_timer.stop()
        self.live_capture_widget.set_preview_running(False)

    def _update_live_preview(self):
        if not self.camera:
            return
        try:
            frame = self.camera.capture()
            self.live_capture_widget.set_preview_frame(frame)
        except IOError as exc:
            self.statusBar().showMessage(f"Preview capture failed: {exc}", 3000)

    # ---- Manual Capture ----
    def _on_manual_capture(self):
        self._capture_and_inspect(live=False)

    # ---- Auto Capture ----
    def _start_auto_capture(self, interval_ms: int):
        # Check up front: previously a missing template opened a warning
        # dialog on every single timer tick.
        if self._ensure_engine() and self._ensure_camera():
            self.auto_capture_timer.start(interval_ms)
            self.live_capture_widget.set_auto_capture_running(True)

    def _on_auto_capture_tick(self):
        if not self._capture_and_inspect(live=True):
            self._stop_auto_capture()

    def _stop_auto_capture(self):
        self.auto_capture_timer.stop()
        self.live_capture_widget.set_auto_capture_running(False)

    # ---- Output Paths ----
    def _on_output_paths_changed(self, pass_dir: str, fail_dir: str):
        # (The I/O Paths tab already confirms the change; this used to show
        # a second, duplicate dialog.)
        try:
            self.namer = OutputFileNamer(pass_dir, fail_dir, scanner=self.namer.scanner)
        except OSError as exc:
            QMessageBox.critical(self, "Invalid Output Folder", f"Could not use these folders:\n{exc}")

    def _on_logging_path_changed(self, log_dir: str):
        if self.inspection_logger.active:
            QMessageBox.warning(self, "Logging Active",
                                "Logging is active — the new folder will be used the next time logging starts.")
        self.inspection_logger.set_logging_dir(log_dir)

    def _on_tesseract_path_changed(self, path: str):
        self.namer.scanner.set_tesseract_path(path)

    # ---- Logging ----
    def _start_logging(self):
        try:
            log_path = self.inspection_logger.start()
        except OSError as exc:
            QMessageBox.critical(self, "Logging Error", f"Could not start logging:\n{exc}")
            return
        self.inspection_widget.set_logging_status(True, str(log_path))

    def _stop_logging(self):
        self.inspection_logger.stop()
        self.inspection_widget.set_logging_status(False)

    def closeEvent(self, event):
        self._stop_outbound()
        self._stop_inbound()
        self.preview_timer.stop()
        self.auto_capture_timer.stop()
        # Let running inspections finish before their signals' receiver goes away.
        self.thread_pool.waitForDone(5000)
        if self.inspection_logger.active:
            self.inspection_logger.stop()
        if self.camera:
            self.camera.release()
            self.camera = None
        event.accept()
