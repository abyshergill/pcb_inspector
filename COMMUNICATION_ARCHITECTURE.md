# Communication Architecture and Examples

This document explains exactly what goes over the network for Mode 1 (Outbound Trigger) and Mode 2 (Inbound Trigger), byte-for-byte, and gives worked examples for connecting a real PLC or another computer.

## 1. Summary

Both modes use **plain raw TCP or UDP sockets** — not a formal industrial protocol like Modbus TCP, EtherNet/IP, or PROFINET. There is no header, no length prefix, no checksum, and no handshake beyond what TCP itself provides. This keeps the implementation simple and universally reachable from any language or platform that can open a socket, but it means:

* It **will** work with any PLC or computer that can send/receive raw TCP or UDP bytes (most PLC families support this via a "socket"/"open communication" instruction block).
* It will **not** natively work with PLCs that only expose Modbus TCP, EtherNet/IP, or PROFINET server/client blocks — those speak a structured protocol, not raw sockets, so an extra gateway or PLC-side raw-socket program is needed (see Section 5).

## 2. Mode 1 — Outbound Trigger (Software Dominant)

### 2.1 What happens

1. The application (acting as a **client**) opens a socket to the configured Host/IP and Port.
2. On every capture-interval tick (configurable in ms), it sends a fixed ASCII payload.
3. Immediately after sending, the application captures a camera frame and runs inspection — it does **not** wait for any reply from the remote device.

### 2.2 Exact wire payload

```
Bytes (hex):   54 52 49 47 47 45 52 0A
Bytes (ASCII): T  R  I  G  G  E  R  \n
```

That is the literal string `"TRIGGER\n"` — 8 bytes, UTF-8/ASCII encoded, newline-terminated. No length prefix, no framing, no sequence number.

### 2.3 UDP vs TCP behavior

* **UDP**: each interval tick sends one independent datagram via `sendto(host, port)`. No connection state; if the target isn't listening, the packet is silently dropped (fire-and-forget).
* **TCP**: a single TCP connection is opened once (on Start), then every interval tick calls `sendall()` on that same connection. **The remote device must already be running a TCP server/listener on that port before you click Start**, or the connection attempt fails silently and no further sends occur until Start is pressed again.

### 2.4 Timing diagram

```
PCB Inspector (client)                    PLC / Camera Controller (server or listener)
        |                                              |
        |----- [TCP connect, if TCP] ----------------->|   (TCP only, once)
        |                                              |
        |----- "TRIGGER\n" ---------------------------->|   at t = 0 ms
        |  (capture frame + inspect locally)            |
        |----- "TRIGGER\n" ---------------------------->|   at t = interval_ms
        |  (capture frame + inspect locally)            |
        |----- "TRIGGER\n" ---------------------------->|   at t = 2 × interval_ms
        |                     ...                       |
```

### 2.5 "Send Test Trigger Now" button

Fires exactly one `"TRIGGER\n"` packet immediately, using the same host/port/protocol currently entered in the form — useful to confirm the PLC or camera reacts before starting the continuous interval loop.

## 3. Mode 2 — Inbound Trigger (Hardware Dominant)

### 3.1 What happens

1. The application (acting as a **server/listener**) binds to a configured Bind Host (typically `0.0.0.0` to accept from any device on the LAN) and Port.
2. It blocks, waiting for incoming data.
3. **Any non-empty payload it receives** — the content is not parsed or validated — immediately triggers a camera capture and starts the inspection pipeline.

### 3.2 Exact wire payload expected

There is **no required payload format**. The listener does not inspect the bytes at all; receiving *anything* is treated as "fire now." This means a PLC can send a single byte, a word, or a full message — all trigger the same action. For the built-in self-test button, the app sends:

```
Bytes (hex):   54 45 53 54 5F 53 49 47 4E 41 4C 0A
Bytes (ASCII): T  E  S  T  _  S  I  G  N  A  L  \n
```

but this exact text is not required — a PLC could send `"1"`, `"GO"`, `0xFF`, or anything non-empty and it would work identically.

### 3.3 UDP vs TCP behavior

* **UDP**: the listener calls `recvfrom()` in a loop — every datagram received (from any sender) fires a capture, indefinitely, with no connection setup needed. This is the simpler and generally recommended choice for Mode 2.
* **TCP**: the listener calls `listen(1)` then `accept()` **once**, then reads from that single connection in a loop. **Important limitation**: only one TCP client connection is accepted for the lifetime of a single "Listen" session. If that client disconnects, the read loop ends and no further signals are processed until you click Stop and Listen again. If your PLC repeatedly opens/closes short-lived TCP connections per trigger, use UDP instead, or see Section 6 for a production hardening note.

### 3.4 Timing diagram

```
PLC / Sensor (client)                     PCB Inspector (server/listener)
        |                                              |
        |                                       [bind + listen/recvfrom]
        |----- [TCP connect, if TCP] ------------------>|   (TCP only, once)
        |                                              |
        |----- <any non-empty bytes> ------------------>|   sensor triggers
        |                                        (capture frame + inspect)
        |----- <any non-empty bytes> ------------------>|   sensor triggers again
        |                                        (capture frame + inspect)
        |                     ...                       |
```

### 3.5 "Send Simulated Signal (Self-Test)" button

Sends the `"TEST_SIGNAL\n"` payload above to `127.0.0.1` (loopback) on the configured port/protocol — lets you confirm the listen → capture → inspect pipeline works before wiring a real PLC or sensor.

## 4. Work with a real PLC?

**Yes, if the PLC supports raw TCP/UDP socket communication** — which most modern PLC platforms do, typically via a dedicated instruction block:

| PLC Family | Raw Socket Capability |
|---|---|
| Siemens S7-1200/1500 | "Open User Communication" instructions (`TSEND_C` / `TRCV_C` for TCP, `TUSEND` / `TURCV` for UDP) can send/receive arbitrary byte payloads to/from any IP:Port. |
| Allen-Bradley / Rockwell (CompactLogix, ControlLogix) | The **Socket Object AOI** (Add-On Instruction, available from Rockwell's sample library) wraps a Winsock-style TCP/UDP client/server directly in ladder logic. |
| Omron | Supports raw socket communication via the **Socket Service** function blocks on NJ/NX controllers. |
| Mitsubishi | Ethernet raw socket communication supported natively on many CPU modules (fixed buffer communication). |
| Generic / any PLC with a scripting or "open Ethernet" block | If it can open a TCP/UDP socket and send/receive bytes, it will work. |

**This will NOT work out-of-the-box** with a PLC that exposes only:
* Modbus TCP (server or client) — this needs a structured Modbus frame (function code, register address, etc.), which this application does not speak.
* EtherNet/IP (implicit or explicit messaging) — needs a CIP-formatted message.
* PROFINET — needs a PROFINET-formatted cyclic/acyclic frame.

For those cases, you have two options:
1. Configure the PLC's raw-socket/open-communication block (if available alongside its Modbus/EtherNet-IP capability — many PLCs support both) to talk directly to this application.
2. Introduce a small protocol gateway (e.g. a lightweight script or industrial gateway device) that receives Modbus/EtherNet-IP on the PLC side and forwards a raw TCP/UDP byte to this application, or vice versa.

## 5. Work with another computer

**Unconditionally.** Since this is a plain socket, any programming language or OS can send/receive it. A few concrete examples:

### 5.1 Python — send a Mode 2 trigger from another computer

```python
import socket

# UDP example
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b"TRIGGER\n", ("192.168.1.50", 6000))  # IP/port of the PCB Inspector PC

# TCP example
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("192.168.1.50", 6000))
sock.sendall(b"TRIGGER\n")
sock.close()
```

### 5.2 PowerShell (Windows) — quick UDP test without writing code

```powershell
$udp = New-Object System.Net.Sockets.UdpClient
$bytes = [System.Text.Encoding]::ASCII.GetBytes("TRIGGER`n")
$udp.Send($bytes, $bytes.Length, "192.168.1.50", 6000)
```

### 5.3 Linux / `netcat` — quick TCP or UDP test from a terminal

```bash
# UDP
echo -n "TRIGGER" | nc -u -w1 192.168.1.50 6000

# TCP (requires the inspector's listener already running)
echo -n "TRIGGER" | nc -w1 192.168.1.50 6000
```

### 5.4 Receiving Mode 1's outbound trigger on another computer (simple Python listener)

```python
import socket

# UDP listener matching Mode 1 settings
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 5000))  # same port configured in Mode 1
while True:
    data, addr = sock.recvfrom(1024)
    print(f"Received trigger: {data} from {addr}")
    # -> fire your camera / PLC input here
```

## 6. Network & Firewall Checklist

* Both PCs/devices must be on the **same subnet or routed** to each other (`ping` should succeed between them first).
* The configured port must be **allowed through the Windows Firewall** (or any OS firewall) on the machine running PCB Inspector, for **inbound** traffic when using Mode 2, and for **outbound** traffic when using Mode 1.
* Only one process can bind to a given UDP/TCP port at a time — stop a previous Listen/Start session before starting another on the same port.
* For **TCP** in Mode 2, remember the current implementation accepts a single persistent client per "Listen" session (see Section 3.3) — prefer UDP if your PLC will reconnect frequently per signal.

## 7. Recommended Hardening for Full Production Deployment

The current implementation intentionally keeps the wire protocol as simple as possible (a bare string) to minimize integration friction. If you move to a larger, multi-line production deployment, consider these upgrades (not yet implemented, flagged here for planning):

* **Acknowledgment replies** — currently neither mode sends a response back to the sender confirming receipt; a PLC integrator may want a reply byte (e.g. `"ACK\n"`) to confirm the trigger was processed.
* **Multi-client TCP accept loop** — so Mode 2's TCP listener can handle a PLC that opens a new short-lived connection per trigger, rather than one persistent connection.
* **Structured payload (length-prefixed or JSON)** — to carry additional metadata per trigger (e.g. a station ID or expected serial number) instead of a bare fire-and-forget signal.
* **Authentication/allow-listing** — the current listener accepts a trigger from any device that can reach the configured port; for a secured line, restrict by source IP or add a shared-secret token in the payload.

These are optional — the current raw-socket design is sufficient for a single-line, trusted-network deployment, which matches most PCB inspection station setups.
