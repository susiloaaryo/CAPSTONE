
import socket
import struct

HOST = "192.168.250.1"
PORT = 502
SOURCE_IP = "192.168.250.2"

UNIT_ID = 2
START_ADDRESS = 0
QUANTITY = 10

def recv_exact(sock, size):
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("HUe menutup koneksi sebelum respons lengkap")
        data += chunk
    return data

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.bind((SOURCE_IP, 0))
        s.connect((HOST, PORT))

        # Modbus TCP FC01: read 6 coils, Unit ID 8
        request = struct.pack(
            ">HHHBBHH",
            1, 0, 6, UNIT_ID, 1,
            START_ADDRESS, QUANTITY
        )

        print(f"Connected to {HOST}:{PORT}")
        print(f"Sending FC01, Unit ID={UNIT_ID}, CS:0..5")
        s.sendall(request)

        header = recv_exact(s, 7)
        length = struct.unpack(">H", header[4:6])[0]
        payload = recv_exact(s, length - 1)

        response = header + payload
        print("Response HEX:", response.hex(" ").upper())

        function_code = response[7]

        if function_code == 0x01:
            byte_count = response[8]
            coil_data = response[9:9 + byte_count]
            print("SUCCESS: Modbus FC01 response received")
            print("Coil data:", coil_data.hex(" ").upper())

        elif function_code == 0x81:
            exception_code = response[8]
            print("Modbus exception response:", exception_code)

        else:
            print("Unexpected function code:", hex(function_code))

except Exception as e:
    print("FAILED:", repr(e))
