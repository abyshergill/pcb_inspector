from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, Signal
import cv2

class InspectionWidget(QWidget):
    """Color/Algorithm views (with pass-fail overlays and live Code
    Region reads) plus Start/Stop Logging controls."""

    startLoggingRequested = Signal()
    stopLoggingRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_image = None
        self._mono_image = None
        self._show_color = True

        self.image_label = QLabel("No image yet")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(640, 480)

        self.toggle_btn = QPushButton("Toggle View: Color")
        self.toggle_btn.clicked.connect(self._toggle_view)
        self.status_label = QLabel("Status: —")

        self.start_log_btn = QPushButton("Start Logging")
        self.stop_log_btn = QPushButton("Stop Logging")
        self.logging_status_label = QLabel("Logging: OFF")
        self.start_log_btn.clicked.connect(self.startLoggingRequested.emit)
        self.stop_log_btn.clicked.connect(self.stopLoggingRequested.emit)

        self.result_list = QListWidget()

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.toggle_btn)
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()
        top_bar.addWidget(self.logging_status_label)
        top_bar.addWidget(self.start_log_btn)
        top_bar.addWidget(self.stop_log_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self.image_label, stretch=3)
        layout.addWidget(self.result_list, stretch=1)

    def display_result(self, result):
        self._color_image = result.annotated_image
        self._mono_image = result.monochrome_image
        self._render()
        self.status_label.setText(
            f"Status: {'PASS' if result.module_passed else 'FAIL'} (Module similarity: {result.module_similarity:.1f}%)"
        )
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

    def _toggle_view(self):
        self._show_color = not self._show_color
        self.toggle_btn.setText(f"Toggle View: {'Color' if self._show_color else 'Algorithm (Mono)'}")
        self._render()

    def _render(self):
        if self._color_image is None:
            return
        image = self._color_image if self._show_color else self._mono_image
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
