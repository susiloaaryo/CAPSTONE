"""Read-only raw Modbus/TCP probe for Saitel HUe CHFLISR.

Pins the TCP source IP to 192.168.250.2 and sends FC01 requests only.
No FC05/FC06/FC15/FC16 writes are sent.

Run: py diagnose_hue_raw_modbus.py
"""
from __future__ import annotations

import socket
import struct
import time

HOST = "192.168.250.1"
PORT = 502
SOURCE_IP = "192.168.250.2"
DEVICES = [
    ("GI SATU", 1, 6),
    ("GD01", 2, 10),
    ("GD02", 3, 10),
    ("GD03", 4, 10),
    ("GD04", 5, 10),
    ("GD05", 6, 10),
    ("GI DUA", 7, 6),
    ("M30_TestBench", 30, 10),
]


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        part = sock.recv(n - len(chunks))
        if not part:
            raise ConnectionError(
                f"peer closed connection after {len(chunks)}/{n} response bytes"
            )
        chunks.extend(part)
    return bytes(chunks)


def probe(name: str, unit_id: int, count: int, tid: int) -> None:
    # Modbus/TCP MBAP: TID(2), PID(2), Length(2), UnitID(1)
    # PDU: FC01(1), StartAddress(2), Quantity(2)
    request = struct.pack(">HHHBBHH", tid, 0, 6, unit_id, 1, 0, count)
    try:
        with socket.create_connection(
            (HOST, PORT), timeout=3, source_address=(SOURCE_IP, 0)
        ) as sock:
            sock.settimeout(3)
            sock.sendall(request)
            header = recv_exact(sock, 7)
            rx_tid, protocol_id, length, rx_uid = struct.unpack(">HHHB", header)
            if length < 2 or length > 260:
                raise ValueError(f"invalid MBAP length={length}; header={header.hex(' ')}")
            pdu = recv_exact(sock, length - 1)
            fc = pdu[0] if pdu else None
            if fc == 0x81 and len(pdu) >= 2:
                print(f"[MODBUS EXCEPTION] {name} UID={unit_id}: code=0x{pdu[1]:02X}; raw={header.hex(' ')} {pdu.hex(' ')}")
            elif fc == 0x01 and len(pdu) >= 2:
                byte_count = pdu[1]
                data = pdu[2:2 + byte_count]
                bits = []
                for i in range(count):
                    byte_i = i // 8
                    bit_i = i % 8
                    bits.append(str((data[byte_i] >> bit_i) & 1) if byte_i < len(data) else "?")
                print(f"[PASS] {name} UID={unit_id} FC01 bits={''.join(bits)}; TID={rx_tid} PID={protocol_id} UIDrx={rx_uid}")
            else:
                print(f"[UNEXPECTED] {name} UID={unit_id}: FC={fc!r}; raw={header.hex(' ')} {pdu.hex(' ')}")
    except Exception as exc:
        print(f"[FAIL] {name} UID={unit_id}: {type(exc).__name__}: {exc}")


def main() -> int:
    print(f"Raw read-only Modbus/TCP probe -> {HOST}:{PORT}, source={SOURCE_IP}")
    print("FC01 only; no write requests.\n")
    passed = 0
    for tid, (name, uid, count) in enumerate(DEVICES, start=1):
        before = time.monotonic()
        # Count PASS and Modbus exception separately; exception proves an MBAP/PDU response.
        try:
            with socket.create_connection((HOST, PORT), timeout=3, source_address=(SOURCE_IP, 0)) as sock:
                sock.settimeout(3)
                request = struct.pack(">HHHBBHH", tid, 0, 6, uid, 1, 0, count)
                sock.sendall(request)
                header = recv_exact(sock, 7)
                rx_tid, protocol_id, length, rx_uid = struct.unpack(">HHHB", header)
                if not 2 <= length <= 260:
                    raise ValueError(f"invalid MBAP length={length}; header={header.hex(' ')}")
                pdu = recv_exact(sock, length - 1)
                fc = pdu[0] if pdu else None
                if fc == 0x01 and len(pdu) >= 2:
                    data = pdu[2:2 + pdu[1]]
                    bits = ''.join(str((data[i//8] >> (i%8)) & 1) if i//8 < len(data) else '?' for i in range(count))
                    print(f"[PASS] {name} UID={uid} FC01 bits={bits}; TID={rx_tid} PID={protocol_id} UIDrx={rx_uid}")
                    passed += 1
                elif fc == 0x81 and len(pdu) >= 2:
                    print(f"[MODBUS EXCEPTION] {name} UID={uid}: code=0x{pdu[1]:02X}; server replied correctly")
                    passed += 1
                else:
                    print(f"[UNEXPECTED] {name} UID={uid}: FC={fc!r}; raw={header.hex(' ')} {pdu.hex(' ')}")
        except Exception as exc:
            print(f"[FAIL] {name} UID={uid}: {type(exc).__name__}: {exc}")
        time.sleep(max(0.05, 0.15 - (time.monotonic() - before)))
    print(f"\nResult: {passed}/{len(DEVICES)} received a Modbus protocol response (normal or exception).")
    return 0 if passed == len(DEVICES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
