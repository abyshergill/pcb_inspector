import socket
import time
from typing import Optional
from PySide6.QtCore import QObject, QTimer, Signal

import config

TRIGGER_PAYLOAD = b"TRIGGER\n"

# After a failed TCP (re)connect, wait this long before the timer tries
# again, so a powered-off PLC doesn't block the GUI on every tick.
RECONNECT_BACKOFF_S = 5.0


class OutboundTriggerController(QObject):
    """Mode 1: Software-Dominant trigger. Sends a trigger command over
    TCP/UDP on a configurable interval, then signals the app to capture.

    triggerSent is emitted only when the packet actually went out, so a
    failed send never results in a capture the PLC did not trigger.
    triggerFailed(str) is emitted with the reason otherwise.
    """

    triggerSent = Signal()
    triggerFailed = Signal(str)

    def __init__(self, host: str, port: int, protocol: str = "UDP", interval_ms: int = 1000,
                 connect_timeout_s: float = config.NETWORK_CONNECT_TIMEOUT_S, parent=None):
        super().__init__(parent)
        self.host = (host or "").strip()
        self.port = int(port)
        self.protocol = protocol.upper()
        self.interval_ms = int(interval_ms)
        self.connect_timeout_s = connect_timeout_s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._sock: Optional[socket.socket] = None
        self._next_reconnect_at = 0.0

    # ---- lifecycle ----
    def start(self) -> None:
        """Connects (TCP) and starts the interval timer. Raises OSError if a
        TCP connection cannot be made, so the UI can report it instead of
        failing silently."""
        if self.protocol == "TCP":
            self._connect()
        self._timer.start(self.interval_ms)

    def stop(self) -> None:
        self._timer.stop()
        self._close()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def set_interval(self, interval_ms: int) -> None:
        self.interval_ms = int(interval_ms)
        if self._timer.isActive():
            self._timer.start(self.interval_ms)

    def send_once(self) -> None:
        """Sends a single trigger packet immediately, independent of the
        timer — used by the 'Send Test Trigger Now' button to verify
        PLC/camera connectivity before starting continuous triggering.
        Raises OSError on failure."""
        self._send()
        self.triggerSent.emit()

    # ---- socket handling ----
    def _connect(self) -> None:
        self._close()
        if self.protocol == "TCP":
            # create_connection applies the timeout to connect() itself, so an
            # unreachable host can't freeze the GUI thread for a minute.
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout_s)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.connect_timeout_s)
        self._sock = sock

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _send(self) -> None:
        if self._sock is None:
            self._connect()
        try:
            if self.protocol == "TCP":
                self._sock.sendall(TRIGGER_PAYLOAD)
            else:
                self._sock.sendto(TRIGGER_PAYLOAD, (self.host, self.port))
        except OSError:
            # A broken TCP socket can never be reused; drop it so the next
            # tick reconnects (e.g. after the PLC restarts).
            self._close()
            raise

    def _on_tick(self) -> None:
        if self._sock is None and time.monotonic() < self._next_reconnect_at:
            self.triggerFailed.emit("not connected (waiting to retry)")
            return
        try:
            self._send()
        except OSError as exc:
            self._next_reconnect_at = time.monotonic() + RECONNECT_BACKOFF_S
            self.triggerFailed.emit(str(exc))
            return
        self.triggerSent.emit()
