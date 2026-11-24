"""Read-only Modbus TCP probe for the seven HUe CHFLISR logical devices.

Run from this project folder while the HUe is connected:
    py diagnose_hue_gateway.py

This script sends FC01 reads only. It never writes coils or issues switching
commands. A separate TCP client is opened for every Unit ID so one timeout
cannot hide the status of later devices.
"""
import asyncio
import logging
from dataclasses import dataclass

from pymodbus.client import AsyncModbusTcpClient

import topologi as T


@dataclass(frozen=True)
class Device:
    name: str
    unit_id: int
    count: int


DEVICES = [
    Device("GI SATU", 1, T.JUMLAH_DI_GI),
    Device("GD01", 2, T.JUMLAH_DI_GD),
    Device("GD02", 3, T.JUMLAH_DI_GD),
    Device("GD03", 4, T.JUMLAH_DI_GD),
    Device("GD04", 5, T.JUMLAH_DI_GD),
    Device("GD05", 6, T.JUMLAH_DI_GD),
    Device("GI DUA", 7, T.JUMLAH_DI_GI),
]


async def probe(device: Device) -> tuple[bool, str]:
    client = AsyncModbusTcpClient(
        T.HOST_HUE_MODBUS,
        port=T.PORT_HUE_MODBUS,
        timeout=3,
        retries=0,
    )
    try:
        connected = await client.connect()
        if not connected or not client.connected:
            return False, (
                f"{device.name}: TCP CONNECT FAILED to "
                f"{T.HOST_HUE_MODBUS}:{T.PORT_HUE_MODBUS}"
            )

        response = await client.read_coils(
            address=0, count=device.count, slave=device.unit_id
        )
        if response is None:
            return False, f"{device.name} UID={device.unit_id}: FC01 returned None"
        if response.isError():
            return False, f"{device.name} UID={device.unit_id}: FC01 Modbus error: {response}"
        if len(response.bits) < device.count:
            return False, (
                f"{device.name} UID={device.unit_id}: only {len(response.bits)} bits, "
                f"expected {device.count}"
            )

        bit_string = "".join("1" if bit else "0" for bit in response.bits[:device.count])
        return True, f"{device.name} UID={device.unit_id}: FC01 CS[0:{device.count - 1}]={bit_string}"
    except Exception as exc:
        return False, (
            f"{device.name} UID={device.unit_id}: {type(exc).__name__}: {exc}; "
            f"socket_connected_after_request={bool(client.connected)}"
        )
    finally:
        client.close()


async def main() -> int:
    print(f"Read-only CHFLISR probe -> {T.HOST_HUE_MODBUS}:{T.PORT_HUE_MODBUS}")
    print("Expected: FC01, GI count=6, GD count=10, logical Unit IDs 1..7.")
    print("No FC05/write requests are sent.\n")

    passed = 0
    for device in DEVICES:
        ok, message = await probe(device)
        print(("[PASS] " if ok else "[FAIL] ") + message)
        passed += int(ok)
        await asyncio.sleep(0.1)

    print(f"\nResult: {passed}/{len(DEVICES)} Unit IDs returned a valid FC01 response.")
    if passed == len(DEVICES):
        print("CHFLISR FC01 status reads are responding for all seven logical devices.")
        return 0
    print("Check the active MDBE bins, CHFLISR channel, remote IP, and downloaded HUe configuration.")
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
