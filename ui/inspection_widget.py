from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QComboBox
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, Signal
import cv2
import numpy as np


def bgr_to_pixmap(image_bgr: np.ndarray) -> QPixmap:
    """Converts a BGR numpy image to a QPixmap (deep copy, so the numpy
    buffer may be freed afterwards)."""
    rgb = np.ascontiguousarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    h, w, ch = rgb.shape
    qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class InspectionWidget(QWidget):
    """Color/Algorithm views (with pass-fail overlays and live Code
    Region reads), active Master Template selection, plus Start/Stop
    Logging controls."""

    startLoggingRequested = Signal()
    stopLoggingRequested = Signal()
    templateSelected = Signal(str)
    refreshTemplatesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_image = None
        self._mono_image = None
        self._show_color = True

        self.image_label = QLabel("No image yet")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 480)

        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(200)
        self.template_combo.setToolTip("Master Template used for inspection")
        self.template_combo.activated.connect(
            lambda _i: self.templateSelected.emit(self.template_combo.currentText())
        )
        self.refresh_templates_btn = QPushButton("Refresh")
        self.refresh_templates_btn.clicked.connect(self.refreshTemplatesRequested.emit)

        self.toggle_btn = QPushButton("Toggle View: Color")
        self.toggle_btn.clicked.connect(self._toggle_view)
        self.status_label = QLabel("Status: —")

        self.start_log_btn = QPushButton("Start Logging")
        self.stop_log_btn = QPushButton("Stop Logging")
        self.stop_log_btn.setEnabled(False)
        self.logging_status_label = QLabel("Logging: OFF")
        self.start_log_btn.clicked.connect(self.startLoggingRequested.emit)
        self.stop_log_btn.clicked.connect(self.stopLoggingRequested.emit)

        self.result_list = QListWidget()

        template_bar = QHBoxLayout()
        template_bar.addWidget(QLabel("Active Template:"))
        template_bar.addWidget(self.template_combo)
        template_bar.addWidget(self.refresh_templates_btn)
        template_bar.addStretch()

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.toggle_btn)
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()
        top_bar.addWidget(self.logging_status_label)
        top_bar.addWidget(self.start_log_btn)
        top_bar.addWidget(self.stop_log_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(template_bar)
        layout.addLayout(top_bar)
        layout.addWidget(self.image_label, stretch=3)
        layout.addWidget(self.result_list, stretch=1)

    def set_templates(self, names: list, active: str | None = None) -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(names)
        if active and active in names:
            self.template_combo.setCurrentText(active)
        self.template_combo.blockSignals(False)

    def display_result(self, result):
        self._color_image = result.annotated_image
        self._mono_image = result.monochrome_image
        self._render()
        self.status_label.setText(
            f"Status: {'PASS' if result.module_passed else 'FAIL'} (Module similarity: {result.module_similarity:.1f}%)"
        )
        self.status_label.setStyleSheet("color: #2e7d32;" if result.module_passed else "color: #c62828;")
        self.result_list.clear()
        for comp in result.component_results:
            tag = "PASS" if comp.passed else "FAIL"
            self.result_list.addItem(f"[{tag}] {comp.name}: {comp.similarity:.1f}%")
        for cr in result.code_region_results:
            label_type = cr.detected_type or cr.configured_type
            text = cr.decoded_text or "Not Found"
            naming_note = "used for naming" if cr.enabled else "not used for naming"
            self.result_list.addItem(f"[CODE:{label_type}] {text} ({naming_note})")

    def set_logging_status(self, active: bool, log_path: str = ""):
        self.logging_status_label.setText(f"Logging: {'ON — ' + log_path if active else 'OFF'}")
        self.start_log_btn.setEnabled(not active)
        self.stop_log_btn.setEnabled(active)

    def _toggle_view(self):
        self._show_color = not self._show_color
        self.toggle_btn.setText(f"Toggle View: {'Color' if self._show_color else 'Algorithm (Mono)'}")
        self._render()

    def _render(self):
        if self._color_image is None:
            return
        image = self._color_image if self._show_color else self._mono_image
        pixmap = bgr_to_pixmap(image).scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()  # keep the image fitted to the new size
