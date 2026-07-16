import socket
from PySide6.QtCore import QThread, Signal

class InboundListenerThread(QThread):
    """Mode 2: Hardware-Dominant trigger. Blocks on a socket in its own
    thread and emits triggerReceived() the instant a PLC/sensor signal
    arrives, without freezing the GUI."""

    triggerReceived = Signal(bytes)
    listenerError = Signal(str)

    def __init__(self, host: str, port: int, protocol: str = "UDP", parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.protocol = protocol.upper()
        self._running = False
        self._sock = None

    def run(self):
        self._running = True
        try:
            if self.protocol == "TCP":
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind((self.host, self.port))
                self._sock.listen(1)
                conn, _ = self._sock.accept()
                while self._running:
                    data = conn.recv(1024)
                    if not data:
                        break
                    self.triggerReceived.emit(data)
            else:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self._sock.bind((self.host, self.port))
                while self._running:
                    data, _ = self._sock.recvfrom(1024)
                    self.triggerReceived.emit(data)
        except OSError as exc:
            self.listenerError.emit(str(exc))
        finally:
            if self._sock:
                self._sock.close()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self.wait(1000)
