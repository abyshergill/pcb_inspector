import socket
import sys
from PySide6.QtCore import QThread, Signal

# How often the blocking socket calls wake up to check whether stop() was
# requested. Closing a socket from another thread does NOT reliably unblock
# accept()/recv() on every OS, so a timeout-based poll is used instead.
_POLL_INTERVAL_S = 0.25


class InboundListenerThread(QThread):
    """Mode 2: Hardware-Dominant trigger. Blocks on a socket in its own
    thread and emits triggerReceived() the instant a PLC/sensor signal
    arrives, without freezing the GUI.

    TCP: accepts clients one after another for the whole Listen session, so
    a PLC (or the self-test button) that opens a short-lived connection per
    trigger keeps working after the first one disconnects.
    UDP: every non-empty datagram is one trigger.
    """

    triggerReceived = Signal(bytes)
    listenerError = Signal(str)
    listening = Signal()  # socket bound successfully

    def __init__(self, host: str, port: int, protocol: str = "UDP", parent=None):
        super().__init__(parent)
        self.host = (host or "").strip()
        self.port = int(port)
        self.protocol = protocol.upper()
        self._running = False
        self._sock = None

    def _make_socket(self) -> socket.socket:
        kind = socket.SOCK_STREAM if self.protocol == "TCP" else socket.SOCK_DGRAM
        sock = socket.socket(socket.AF_INET, kind)
        # SO_REUSEADDR lets a TCP listener restart right after Stop (TIME_WAIT).
        # Not used for UDP (it would let two listeners silently share a port)
        # and not on Windows, where it means "steal the port" instead.
        if self.protocol == "TCP" and sys.platform != "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(_POLL_INTERVAL_S)
        sock.bind((self.host, self.port))
        return sock

    def run(self):
        self._running = True
        try:
            self._sock = self._make_socket()
            self.listening.emit()
            if self.protocol == "TCP":
                self._serve_tcp()
            else:
                self._serve_udp()
        except OSError as exc:
            if self._running:  # errors caused by stop() are not real errors
                self.listenerError.emit(str(exc))
        finally:
            self._running = False
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    def _serve_udp(self):
        while self._running:
            try:
                data, _ = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # Windows reports ICMP "port unreachable" from an earlier
                # sendto as a reset on the next recvfrom; it is harmless.
                continue
            if data:
                self.triggerReceived.emit(data)

    def _serve_tcp(self):
        self._sock.listen(5)
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(_POLL_INTERVAL_S)
                while self._running:
                    try:
                        data = conn.recv(4096)
                    except socket.timeout:
                        continue
                    except (ConnectionResetError, ConnectionAbortedError):
                        break
                    if not data:
                        break  # client closed; go back to accept() for the next one
                    self.triggerReceived.emit(data)

    def stop(self, timeout_ms: int = 2000) -> None:
        self._running = False
        self.wait(timeout_ms)
