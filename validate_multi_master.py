"""Check direct and EBC-downstream Unit IDs on all seven RTU simulators.

Run after all seven RTU simulator processes have started:
    py validate_multi_master.py

This checks local RTU aliases and the exact downstream Unit IDs from the
uploaded NEWEST.ebc project. It does not emulate the physical HUe gateway.
"""
import asyncio
import logging
from dataclasses import dataclass

from pymodbus.client import AsyncModbusTcpClient

import topologi as T

TIMEOUT_S = 3

@dataclass(frozen=True)
class RTU:
    name: str
    host: str
    count: int
    ebc_unit_id: int

RTUS = [
    RTU("GI A / GI SATU", "192.168.250.3", 6, 1),
    RTU("GD01", "192.168.250.9", 10, 2),
    RTU("GD02", "192.168.250.5", 10, 2),
    RTU("GD03", "192.168.250.6", 10, 3),
    RTU("GD04", "192.168.250.7", 10, 4),
    RTU("GD05", "192.168.250.8", 10, 2),
    RTU("GI B / GI DUA", "192.168.250.4", 6, 3),
]

async def read_as_client(label: str, rtu: RTU, unit_id: int) -> tuple[bool, str]:
    client = AsyncModbusTcpClient(rtu.host, port=502, timeout=TIMEOUT_S, retries=0)
    try:
        connected = await client.connect()
        if not connected or not client.connected:
            return False, f"{label} -> {rtu.name} ({rtu.host}:502 UID={unit_id}): CONNECT FAILED"
        response = await client.read_coils(address=0, count=rtu.count, slave=unit_id)
        if response is None or response.isError():
            return False, f"{label} -> {rtu.name} ({rtu.host}:502 UID={unit_id}): FC01 ERROR: {response}"
        bits = "".join("1" if b else "0" for b in response.bits[:rtu.count])
        return True, f"{label} -> {rtu.name} ({rtu.host}:502 UID={unit_id}): FC01[0:{rtu.count-1}]={bits}"
    except Exception as exc:
        return False, f"{label} -> {rtu.name} ({rtu.host}:502 UID={unit_id}): ERROR: {exc}"
    finally:
        client.close()

async def main() -> int:
    print("Testing FC01 status reads via direct Unit ID 1 and exact EBC downstream Unit IDs.")
    print("Start all seven RTU processes first. This does not replace a live HUe test.\n")
    tasks = []
    for rtu in RTUS:
        tasks.append(read_as_client("direct/local", rtu, T.SLAVE_RTU))
        if rtu.ebc_unit_id != T.SLAVE_RTU:
            tasks.append(read_as_client("EBC MDBM", rtu, rtu.ebc_unit_id))
    results = await asyncio.gather(*tasks)
    for ok, line in results:
        print(("[PASS] " if ok else "[FAIL] ") + line)
    passed = sum(1 for ok, _ in results if ok)
    print(f"\nResult: {passed}/{len(results)} FC01 reads passed.")
    if passed == len(results):
        print("All configured RTU Unit ID aliases accepted the status reads.")
        return 0
    print("Check simulator logs, EBC downstream Unit IDs, IP aliases, firewall, and TCP/502 listeners.")
    return 1

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
