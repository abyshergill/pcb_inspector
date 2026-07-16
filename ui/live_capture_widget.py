from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QFormLayout, QGroupBox
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Signal, Qt
import cv2

class LiveCaptureWidget(QWidget):
    """Dedicated tab for live camera preview plus manual and interval-based
    automatic capture, independent of the PLC/hardware trigger modes."""

    livePreviewStartRequested = Signal()
    livePreviewStopRequested = Signal()
    manualCaptureRequested = Signal()
    autoCaptureStartRequested = Signal(int)
    autoCaptureStopRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.preview_label = QLabel("No live preview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(640, 480)
        self.preview_label.setStyleSheet("background-color: #111; color: #888;")

        preview_btn_row = QHBoxLayout()
        self.start_preview_btn = QPushButton("Start Live Preview")
        self.stop_preview_btn = QPushButton("Stop Live Preview")
        preview_btn_row.addWidget(self.start_preview_btn)
        preview_btn_row.addWidget(self.stop_preview_btn)
        self.start_preview_btn.clicked.connect(self.livePreviewStartRequested.emit)
        self.stop_preview_btn.clicked.connect(self.livePreviewStopRequested.emit)

        manual_group = QGroupBox("Manual Capture")
        manual_layout = QVBoxLayout(manual_group)
        self.manual_capture_btn = QPushButton("Capture Now")
        manual_layout.addWidget(self.manual_capture_btn)
        self.manual_capture_btn.clicked.connect(self.manualCaptureRequested.emit)

        auto_group = QGroupBox("Auto Capture (Local Timer)")
        auto_layout = QVBoxLayout(auto_group)
        auto_form = QFormLayout()
        self.auto_interval_spin = QSpinBox()
        self.auto_interval_spin.setRange(100, 3600000)
        self.auto_interval_spin.setValue(5000)
        auto_form.addRow("Interval (ms):", self.auto_interval_spin)
        auto_layout.addLayout(auto_form)
        auto_btn_row = QHBoxLayout()
        self.auto_start_btn = QPushButton("Start Auto Capture")
        self.auto_stop_btn = QPushButton("Stop Auto Capture")
        auto_btn_row.addWidget(self.auto_start_btn)
        auto_btn_row.addWidget(self.auto_stop_btn)
        auto_layout.addLayout(auto_btn_row)
        self.auto_start_btn.clicked.connect(
            lambda: self.autoCaptureStartRequested.emit(self.auto_interval_spin.value())
        )
        self.auto_stop_btn.clicked.connect(self.autoCaptureStopRequested.emit)

        side_row = QHBoxLayout()
        side_row.addWidget(manual_group)
        side_row.addWidget(auto_group)

        layout = QVBoxLayout(self)
        layout.addLayout(preview_btn_row)
        layout.addWidget(self.preview_label, stretch=1)
        layout.addLayout(side_row)

    def set_preview_frame(self, frame_bgr) -> None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(pixmap)
