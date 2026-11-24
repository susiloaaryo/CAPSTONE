import socket

HOST = "192.168.250.1"
PORT = 1503

print(f"[TARGET] {HOST}:{PORT}")

REQUEST = bytes.fromhex(
    "00 01 00 00 00 06 01 01 00 00 00 06"
)

def recv_exact(sock, size):
    data = bytearray()

    while len(data) < size:
        chunk = sock.recv(size - len(data))

        if not chunk:
            break

        data.extend(chunk)

    return bytes(data)


try:
    with socket.create_connection(
        (HOST, PORT), timeout=3
    ) as sock:

        sock.settimeout(3)

        print("[TCP] Connected")
        print("[TX]", REQUEST.hex(" "))

        sock.sendall(REQUEST)

        header = recv_exact(sock, 7)

        if len(header) != 7:
            print("[FAIL] HUe closed or incomplete MBAP header")
        else:
            length = int.from_bytes(header[4:6], "big")
            pdu = recv_exact(sock, length - 1)

            print("[RX]", (header + pdu).hex(" "))

            if len(pdu) != length - 1:
                print("[FAIL] Incomplete Modbus response")

            elif pdu[0] == 0x01:
                print("[PASS] Valid FC01 response")
                print("[DATA]", pdu.hex(" "))

            elif pdu[0] == 0x81:
                print("[EXCEPTION] Modbus error:", pdu[1])

            else:
                print("[UNKNOWN] Function:", hex(pdu[0]))

except ConnectionResetError:
    print("[FAIL] HUe RESET connection")

except socket.timeout:
    print("[FAIL] HUe TIMEOUT")

except OSError as e:
    print("[SOCKET ERROR]", repr(e))