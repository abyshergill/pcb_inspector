import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QGroupBox,
    QFileDialog, QHBoxLayout, QMessageBox, QLabel
)
from PySide6.QtCore import Signal
from core.app_settings import AppSettings

class OutputPathsWidget(QWidget):
    """Pass/Fail folders, Golden Image location, Inspection Logging path,
    and the OCR engine (Tesseract) path — with automatic EasyOCR fallback
    when no Tesseract path is configured."""

    outputPathsChanged = Signal(str, str)
    goldenImageUploaded = Signal(str)
    loggingPathChanged = Signal(str)
    tesseractPathChanged = Signal(str)

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.settings = settings

        # ---- Pass / Fail folders ----
        pf_group = QGroupBox("Pass / Fail Output Folders")
        pf_form = QFormLayout(pf_group)
        self.pass_dir_edit = QLineEdit(self.settings.pass_dir)
        self.fail_dir_edit = QLineEdit(self.settings.fail_dir)
        pass_browse_btn = QPushButton("Browse...")
        fail_browse_btn = QPushButton("Browse...")
        pass_row = QHBoxLayout(); pass_row.addWidget(self.pass_dir_edit); pass_row.addWidget(pass_browse_btn)
        fail_row = QHBoxLayout(); fail_row.addWidget(self.fail_dir_edit); fail_row.addWidget(fail_browse_btn)
        pf_form.addRow("Pass Folder:", pass_row)
        pf_form.addRow("Fail Folder:", fail_row)
        apply_pf_btn = QPushButton("Apply Pass/Fail Paths")
        pf_form.addRow(apply_pf_btn)
        pass_browse_btn.clicked.connect(lambda: self._browse_folder(self.pass_dir_edit))
        fail_browse_btn.clicked.connect(lambda: self._browse_folder(self.fail_dir_edit))
        apply_pf_btn.clicked.connect(self._apply_pass_fail_paths)

        # ---- Golden image location ----
        golden_group = QGroupBox("Golden Image Location")
        golden_layout = QVBoxLayout(golden_group)
        golden_form = QFormLayout()
        self.golden_dir_edit = QLineEdit(self.settings.golden_image_dir)
        golden_browse_btn = QPushButton("Browse...")
        golden_row = QHBoxLayout(); golden_row.addWidget(self.golden_dir_edit); golden_row.addWidget(golden_browse_btn)
        golden_form.addRow("Default Save Folder:", golden_row)
        apply_golden_btn = QPushButton("Apply Golden Image Folder")
        golden_form.addRow(apply_golden_btn)
        golden_layout.addLayout(golden_form)
        golden_browse_btn.clicked.connect(lambda: self._browse_folder(self.golden_dir_edit))
        apply_golden_btn.clicked.connect(self._apply_golden_dir)

        upload_row = QHBoxLayout()
        self.upload_golden_btn = QPushButton("Upload Existing Golden Image...")
        upload_row.addWidget(self.upload_golden_btn)
        golden_layout.addLayout(upload_row)
        golden_layout.addWidget(QLabel("Skips building from reference photos — loads your chosen image directly into Training."))
        self.upload_golden_btn.clicked.connect(self._upload_golden_image)

        # ---- Inspection logging path ----
        log_group = QGroupBox("Inspection Logging Path")
        log_layout = QVBoxLayout(log_group)
        log_form = QFormLayout()
        self.log_dir_edit = QLineEdit(self.settings.logging_dir)
        log_browse_btn = QPushButton("Browse...")
        log_row = QHBoxLayout(); log_row.addWidget(self.log_dir_edit); log_row.addWidget(log_browse_btn)
        log_form.addRow("Log Folder:", log_row)
        apply_log_btn = QPushButton("Apply Logging Path")
        log_form.addRow(apply_log_btn)
        log_layout.addLayout(log_form)
        log_layout.addWidget(QLabel("Start/Stop Logging controls are on the Live Inspection tab."))
        log_browse_btn.clicked.connect(lambda: self._browse_folder(self.log_dir_edit))
        apply_log_btn.clicked.connect(self._apply_logging_path)

        # ---- OCR engine (Tesseract) path ----
        ocr_group = QGroupBox("OCR Engine — Tesseract (optional)")
        ocr_layout = QVBoxLayout(ocr_group)
        ocr_form = QFormLayout()
        self.tesseract_path_edit = QLineEdit(self.settings.tesseract_path)
        tesseract_browse_btn = QPushButton("Browse...")
        tesseract_row = QHBoxLayout()
        tesseract_row.addWidget(self.tesseract_path_edit)
        tesseract_row.addWidget(tesseract_browse_btn)
        ocr_form.addRow("tesseract.exe Path:", tesseract_row)
        apply_tesseract_btn = QPushButton("Apply Tesseract Path")
        ocr_form.addRow(apply_tesseract_btn)
        ocr_layout.addLayout(ocr_form)
        self.tesseract_status_label = QLabel()
        ocr_layout.addWidget(self.tesseract_status_label)
        self._refresh_tesseract_status()
        tesseract_browse_btn.clicked.connect(self._browse_tesseract_exe)
        apply_tesseract_btn.clicked.connect(self._apply_tesseract_path)

        layout = QVBoxLayout(self)
        layout.addWidget(pf_group)
        layout.addWidget(golden_group)
        layout.addWidget(log_group)
        layout.addWidget(ocr_group)
        layout.addStretch()

    def _browse_folder(self, target_edit: QLineEdit):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            target_edit.setText(folder)

    def _apply_pass_fail_paths(self):
        pass_dir = self.pass_dir_edit.text().strip()
        fail_dir = self.fail_dir_edit.text().strip()
        if not pass_dir or not fail_dir:
            QMessageBox.warning(self, "Invalid Paths", "Both Pass and Fail folder paths are required.")
            return
        self.settings.pass_dir = pass_dir
        self.settings.fail_dir = fail_dir
        self.outputPathsChanged.emit(pass_dir, fail_dir)
        QMessageBox.information(self, "Paths Updated", f"Pass folder: {pass_dir}\nFail folder: {fail_dir}")

    def _apply_golden_dir(self):
        golden_dir = self.golden_dir_edit.text().strip()
        if not golden_dir:
            QMessageBox.warning(self, "Invalid Path", "Golden Image folder is required.")
            return
        os.makedirs(golden_dir, exist_ok=True)
        self.settings.golden_image_dir = golden_dir
        QMessageBox.information(self, "Golden Image Folder Updated", f"New Golden Images will default to: {golden_dir}")

    def _upload_golden_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Existing Golden Image", self.settings.golden_image_dir, "Images (*.png *.jpg *.bmp)"
        )
        if path:
            self.goldenImageUploaded.emit(path)
            QMessageBox.information(self, "Golden Image Loaded", f"'{os.path.basename(path)}' loaded into the Training tab.")

    def _apply_logging_path(self):
        log_dir = self.log_dir_edit.text().strip()
        if not log_dir:
            QMessageBox.warning(self, "Invalid Path", "Logging folder is required.")
            return
        os.makedirs(log_dir, exist_ok=True)
        self.settings.logging_dir = log_dir
        self.loggingPathChanged.emit(log_dir)
        QMessageBox.information(self, "Logging Path Updated", f"Inspection logs will be saved to: {log_dir}")

    def _browse_tesseract_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select tesseract Executable", "", "Executable (*.exe);;All Files (*)"
        )
        if path:
            self.tesseract_path_edit.setText(path)

    def _apply_tesseract_path(self):
        path = self.tesseract_path_edit.text().strip()
        self.settings.tesseract_path = path
        self.tesseractPathChanged.emit(path)
        self._refresh_tesseract_status()
        if path and os.path.isfile(path):
            QMessageBox.information(self, "Tesseract Configured", f"OCR will use Tesseract at: {path}")
        else:
            QMessageBox.information(self, "Tesseract Cleared", "No valid Tesseract path set — OCR will automatically use EasyOCR instead.")

    def _refresh_tesseract_status(self):
        path = self.settings.tesseract_path
        if path and os.path.isfile(path):
            self.tesseract_status_label.setText(f"✔ Tesseract configured: {path}")
            self.tesseract_status_label.setStyleSheet("color: #2e7d32;")
        else:
            self.tesseract_status_label.setText(
                "⚠ Tesseract path not set — OCR will automatically use EasyOCR instead (no extra setup needed)."
            )
            self.tesseract_status_label.setStyleSheet("color: #e65100;")
