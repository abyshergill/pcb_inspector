import socket
from PySide6.QtCore import QObject, QTimer, Signal

class OutboundTriggerController(QObject):
    """Mode 1: Software-Dominant trigger. Sends a trigger command over
    TCP/UDP on a configurable interval, then signals the app to capture."""

    triggerSent = Signal()

    def __init__(self, host: str, port: int, protocol: str = "UDP", interval_ms: int = 1000):
        super().__init__()
        self.host = host
        self.port = port
        self.protocol = protocol.upper()
        self.interval_ms = interval_ms
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fire_trigger)
        self._sock = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM if self.protocol == "TCP" else socket.SOCK_DGRAM
        )
        self._connected = False

    def start(self):
        self._ensure_connected()
        self._timer.start(self.interval_ms)

    def stop(self):
        self._timer.stop()

    def set_interval(self, interval_ms: int):
        self.interval_ms = interval_ms
        if self._timer.isActive():
            self._timer.start(interval_ms)

    def send_once(self):
        """Sends a single trigger packet immediately, independent of the
        timer — used by the 'Send Test Trigger Now' button to verify
        PLC/camera connectivity before starting continuous triggering."""
        self._ensure_connected()
        self._fire_trigger()

    def _ensure_connected(self):
        if self.protocol == "TCP" and not self._connected:
            try:
                self._sock.connect((self.host, self.port))
                self._connected = True
            except OSError:
                pass

    def _fire_trigger(self):
        payload = b"TRIGGER\n"
        try:
            if self.protocol == "TCP":
                self._sock.sendall(payload)
            else:
                self._sock.sendto(payload, (self.host, self.port))
        except OSError as exc:
            print(f"[OutboundTrigger] send failed: {exc}")
        self.triggerSent.emit()
