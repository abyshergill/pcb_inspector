import socket
import time

import pytest

from networking.inbound_listener import InboundListenerThread
from networking.outbound_trigger import OutboundTriggerController, TRIGGER_PAYLOAD


def _free_port(kind=socket.SOCK_DGRAM):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_outbound_udp_send_once(qtbot):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    ctrl = OutboundTriggerController("127.0.0.1", rx.getsockname()[1], "UDP")
    with qtbot.waitSignal(ctrl.triggerSent, timeout=1000):
        ctrl.send_once()
    assert rx.recvfrom(64)[0] == TRIGGER_PAYLOAD
    ctrl.stop()
    rx.close()


def test_outbound_udp_timer(qtbot):
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    ctrl = OutboundTriggerController("127.0.0.1", rx.getsockname()[1], "UDP", interval_ms=30)
    ctrl.start()
    with qtbot.waitSignal(ctrl.triggerSent, timeout=2000):
        pass
    assert ctrl.is_running()
    ctrl.stop()
    assert not ctrl.is_running()
    assert rx.recvfrom(64)[0] == TRIGGER_PAYLOAD
    rx.close()


def test_outbound_tcp_connect_failure_raises(qtbot):
    port = _free_port(socket.SOCK_STREAM)  # nothing listening
    ctrl = OutboundTriggerController("127.0.0.1", port, "TCP", connect_timeout_s=1)
    with pytest.raises(OSError):
        ctrl.start()
    with pytest.raises(OSError):
        ctrl.send_once()
    assert not ctrl.is_running()


def test_outbound_tcp_sends(qtbot):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(2)
    ctrl = OutboundTriggerController("127.0.0.1", srv.getsockname()[1], "TCP")
    ctrl.send_once()
    conn, _ = srv.accept()
    conn.settimeout(2)
    assert conn.recv(64) == TRIGGER_PAYLOAD
    ctrl.stop()
    conn.close()
    srv.close()


def _start_listener(qtbot, protocol):
    kind = socket.SOCK_STREAM if protocol == "TCP" else socket.SOCK_DGRAM
    port = _free_port(kind)
    t = InboundListenerThread("127.0.0.1", port, protocol)
    with qtbot.waitSignal(t.listening, timeout=2000):
        t.start()
    return t, port


def test_inbound_udp(qtbot):
    t, port = _start_listener(qtbot, "UDP")
    try:
        with qtbot.waitSignal(t.triggerReceived, timeout=2000) as blocker:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(b"GO", ("127.0.0.1", port))
        assert blocker.args == [b"GO"]
    finally:
        t.stop()
    assert not t.isRunning()


def test_inbound_tcp_accepts_successive_clients(qtbot):
    # Regression: the listener used to die after the first client disconnected.
    t, port = _start_listener(qtbot, "TCP")
    try:
        for payload in (b"one", b"two", b"three"):
            with qtbot.waitSignal(t.triggerReceived, timeout=2000) as blocker:
                with socket.create_connection(("127.0.0.1", port), timeout=2) as c:
                    c.sendall(payload)
            assert blocker.args == [payload]
    finally:
        t.stop()
    assert not t.isRunning()


def test_inbound_stop_emits_no_error(qtbot):
    t, _ = _start_listener(qtbot, "TCP")
    errors = []
    t.listenerError.connect(errors.append)
    start = time.monotonic()
    t.stop()
    assert time.monotonic() - start < 2
    qtbot.wait(50)
    assert errors == [] and not t.isRunning()


def test_inbound_port_in_use_reports_error(qtbot):
    blocker_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker_sock.bind(("127.0.0.1", 0))
    port = blocker_sock.getsockname()[1]
    t = InboundListenerThread("127.0.0.1", port, "UDP")
    with qtbot.waitSignal(t.listenerError, timeout=2000):
        t.start()
    t.stop()
    blocker_sock.close()
