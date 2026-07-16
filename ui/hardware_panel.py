import socket
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QSpinBox,
    QPushButton, QGroupBox, QFileDialog, QHBoxLayout, QLabel, QDialog,
    QTextBrowser, QMessageBox
)
from PySide6.QtCore import Signal

INSTRUCTIONS_HTML = """
<h3>How to Sync PCB Inspector with Hardware</h3>

<p><b>Mode 1 — Outbound Trigger (Software Dominant)</b><br>
Use this when the PC/software should control capture timing (e.g. driving a PLC or camera trigger input).</p>
<ul>
<li>The app sends a small packet (<code>TRIGGER</code>) to the configured <b>Host/IP</b> and <b>Port</b>,
repeating every <b>Capture Interval</b> (ms), using the selected <b>Protocol</b> (TCP or UDP).</li>
<li>Configure your PLC/camera controller to listen on that same IP:Port for the protocol you chose.</li>
<li><b>TCP:</b> the target device must already be running a TCP server on that port before you click Start.</li>
<li><b>UDP:</b> no persistent connection is needed, but confirm the firewall on the receiving device allows
inbound UDP traffic on that port.</li>
<li>Use <b>Send Test Trigger Now</b> to fire a single packet immediately and confirm the PLC/camera reacts,
before starting continuous triggering.</li>
</ul>

<p><b>Mode 2 — Inbound Trigger (Hardware Dominant)</b><br>
Use this when a PLC or physical sensor should decide when to capture (e.g. a part-present sensor).</p>
<ul>
<li>The app opens a listener on the configured <b>Bind Host</b> (usually <code>0.0.0.0</code> to accept from any
device on the network) and <b>Port</b>, using the selected <b>Protocol</b>.</li>
<li>Configure your PLC/sensor to send its trigger signal to this PC's IP address, on that same port, using the
same protocol.</li>
<li>Any non-empty message received instantly fires a camera capture and starts inspection — the payload
content itself does not need to match anything specific.</li>
<li>After clicking <b>Listen</b>, use <b>Send Simulated Signal (Self-Test)</b> to simulate a PLC signal locally
and confirm the listener → capture → inspection pipeline works before wiring real hardware.</li>
</ul>

<p><b>Batch Testing Mode (Offline)</b><br>
No network connection required — validate your Master Template and thresholds against existing images before
going live with either hardware mode.</p>

<p><b>Troubleshooting</b></p>
<ul>
<li>If nothing happens after Start/Listen, confirm the IP is reachable (same subnet or routed) and no firewall
blocks the chosen port.</li>
<li>TCP requires a listener/server already running on the other end; use UDP for simpler initial testing.</li>
<li>Only one process can bind to a given port at a time — stop any previous run before starting again.</li>
</ul>
"""

class HardwareSyncPanel(QWidget):
    """UI for Mode 1 (Outbound), Mode 2 (Inbound), Batch Testing, plus
    connectivity self-test tools and built-in setup instructions."""

    startOutboundRequested = Signal(dict)
    stopOutboundRequested = Signal()
    testTriggerRequested = Signal(dict)

    startInboundRequested = Signal(dict)
    stopInboundRequested = Signal()

    batchImageRequested = Signal(str)
    batchFolderRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        instructions_btn = QPushButton("How to Sync Hardware (Instructions)")
        instructions_btn.clicked.connect(self._show_instructions)
        layout.addWidget(instructions_btn)

        # ---- Mode 1: Outbound ----
        out_group = QGroupBox("Mode 1 — Outbound Trigger (Software Dominant)")
        out_form = QFormLayout(out_group)
        self.out_host = QLineEdit("192.168.1.10")
        self.out_port = QSpinBox(); self.out_port.setRange(1, 65535); self.out_port.setValue(5000)
        self.out_protocol = QComboBox(); self.out_protocol.addItems(["UDP", "TCP"])
        self.out_interval = QSpinBox(); self.out_interval.setRange(10, 600000); self.out_interval.setValue(1000)

        out_btn_row = QHBoxLayout()
        self.out_start_btn = QPushButton("Start")
        self.out_stop_btn = QPushButton("Stop")
        self.out_test_btn = QPushButton("Send Test Trigger Now")
        out_btn_row.addWidget(self.out_start_btn)
        out_btn_row.addWidget(self.out_stop_btn)
        out_btn_row.addWidget(self.out_test_btn)

        self.out_status_label = QLabel("Status: Idle")

        out_form.addRow("Host/IP:", self.out_host)
        out_form.addRow("Port:", self.out_port)
        out_form.addRow("Protocol:", self.out_protocol)
        out_form.addRow("Capture Interval (ms):", self.out_interval)
        out_form.addRow(out_btn_row)
        out_form.addRow(self.out_status_label)

        self.out_start_btn.clicked.connect(self._emit_start_outbound)
        self.out_stop_btn.clicked.connect(self.stopOutboundRequested.emit)
        self.out_test_btn.clicked.connect(self._emit_test_trigger)

        # ---- Mode 2: Inbound ----
        in_group = QGroupBox("Mode 2 — Inbound Trigger (Hardware Dominant)")
        in_form = QFormLayout(in_group)
        self.in_host = QLineEdit("0.0.0.0")
        self.in_port = QSpinBox(); self.in_port.setRange(1, 65535); self.in_port.setValue(6000)
        self.in_protocol = QComboBox(); self.in_protocol.addItems(["UDP", "TCP"])

        in_btn_row = QHBoxLayout()
        self.in_start_btn = QPushButton("Listen")
        self.in_stop_btn = QPushButton("Stop")
        self.in_test_btn = QPushButton("Send Simulated Signal (Self-Test)")
        in_btn_row.addWidget(self.in_start_btn)
        in_btn_row.addWidget(self.in_stop_btn)
        in_btn_row.addWidget(self.in_test_btn)

        self.in_status_label = QLabel("Status: Not Listening")

        in_form.addRow("Bind Host:", self.in_host)
        in_form.addRow("Port:", self.in_port)
        in_form.addRow("Protocol:", self.in_protocol)
        in_form.addRow(in_btn_row)
        in_form.addRow(self.in_status_label)

        self.in_start_btn.clicked.connect(self._emit_start_inbound)
        self.in_stop_btn.clicked.connect(self.stopInboundRequested.emit)
        self.in_test_btn.clicked.connect(self._send_simulated_signal)

        # ---- Batch Testing ----
        batch_group = QGroupBox("Batch Testing Mode (Offline)")
        batch_layout = QVBoxLayout(batch_group)
        batch_btn_row = QHBoxLayout()
        self.batch_image_btn = QPushButton("Upload Single Image")
        self.batch_folder_btn = QPushButton("Upload Folder")
        batch_btn_row.addWidget(self.batch_image_btn)
        batch_btn_row.addWidget(self.batch_folder_btn)
        batch_layout.addLayout(batch_btn_row)
        self.batch_image_btn.clicked.connect(self._select_batch_image)
        self.batch_folder_btn.clicked.connect(self._select_batch_folder)

        layout.addWidget(out_group)
        layout.addWidget(in_group)
        layout.addWidget(batch_group)
        layout.addStretch()

    def _show_instructions(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Hardware Sync — Instructions")
        dialog.resize(640, 560)
        dialog_layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(INSTRUCTIONS_HTML)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        dialog_layout.addWidget(browser)
        dialog_layout.addWidget(close_btn)
        dialog.exec()

    def _emit_start_outbound(self):
        self.startOutboundRequested.emit({
            "host": self.out_host.text(), "port": self.out_port.value(),
            "protocol": self.out_protocol.currentText(), "interval_ms": self.out_interval.value(),
        })

    def _emit_test_trigger(self):
        self.testTriggerRequested.emit({
            "host": self.out_host.text(), "port": self.out_port.value(),
            "protocol": self.out_protocol.currentText(), "interval_ms": self.out_interval.value(),
        })

    def _emit_start_inbound(self):
        self.startInboundRequested.emit({
            "host": self.in_host.text(), "port": self.in_port.value(),
            "protocol": self.in_protocol.currentText(),
        })

    def _send_simulated_signal(self):
        host = self.in_host.text().strip()
        target_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
        port = self.in_port.value()
        protocol = self.in_protocol.currentText()
        payload = b"TEST_SIGNAL\n"
        try:
            if protocol == "TCP":
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    s.connect((target_host, port))
                    s.sendall(payload)
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.sendto(payload, (target_host, port))
            QMessageBox.information(
                self, "Test Signal Sent", f"Sent a simulated trigger to {target_host}:{port} ({protocol})."
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Test Signal Failed",
                f"Could not send test signal: {exc}\nMake sure 'Listen' is active first."
            )

    def _select_batch_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select PCB Image", "", "Images (*.png *.jpg *.bmp)")
        if path:
            self.batchImageRequested.emit(path)

    def _select_batch_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select PCB Image Folder")
        if folder:
            self.batchFolderRequested.emit(folder)
