"""System Behavior simulator - final FLISR testbench.

HMI is the only writer to this port.
Controller does not read port 8027.

8027:
    HR0 = CASE
    HR1 = MODE
    HR2 = REPAIR

RTU contract injection:
    GI 8020/8026:
        HR0 forced trip
        HR1 forced UV
        HR2 forced current
        HR3 forced voltage
    GD 8021..8025:
        HR0 forced HFD1
        HR1 forced HFD2
        HR2 forced current LBS1
        HR3 forced current LBS2
        HR4 forced voltage

Simulator-only:
    fault_state.json globally pauses CSV progression on all seven RTUs.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

import topologi as T


HOST = "127.0.0.1"
PORT = 8027
SLAVE = T.SLAVE_RTU

HR_CASE = 0
HR_MODE = 1
HR_REPAIR = 2

GI_PORTS = {8020, 8026}
GD_PORTS = {8021, 8022, 8023, 8024, 8025}
RTU_PORTS = sorted(GI_PORTS | GD_PORTS)

STATE_FILE = Path(__file__).with_name(
    "fault_state.json"
)

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)


def set_global_state(case: int) -> bool:
    payload = {
        "case": int(case),
        "active": int(case) != 0,
    }
    text = json.dumps(payload, separators=(",", ":"))

    # Retry briefly because Windows file handles can be transiently busy.
    for attempt in range(10):
        try:
            with STATE_FILE.open("w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            return True
        except PermissionError as exc:
            if attempt == 9:
                logging.error(
                    "Gagal menulis %s setelah %d percobaan: %s",
                    STATE_FILE.name,
                    attempt + 1,
                    exc,
                )
            else:
                # 20, 40, ... 200 ms
                import time
                time.sleep(0.02 * (attempt + 1))
        except OSError as exc:
            logging.error(
                "Gagal menulis %s: %s",
                STATE_FILE.name,
                exc,
            )
            return False

    return False


def injection_for_case(case: int):

    case = int(case)
    result = {port: {} for port in RTU_PORTS}

    if case == 0:
        return result

    # ------------------------------------------------------------
    # Faults initiated from GI SATU (left side): K1-K3
    # K1: no GD HFD -> localization fallback gives segment 0.
    # K2: HFD2 at GD01.
    # K3: HFD2 at GD01 + GD02.
    # ------------------------------------------------------------
    if case in (1, 2, 3):
        result[8020][0] = 1          # GI SATU HR0 = forced trip
        for gd in range(1, case):
            result[8020 + gd][1] = 1  # GD HR1 = forced HFD2
        return result

    # ------------------------------------------------------------
    # Faults initiated from GI DUA (right side): K4-K6
    # K4: HFD1 at GD05 + GD04 -> segment 3 (GD03-GD04).
    # K5: HFD1 at GD05 -> segment 4.
    # K6: no GD HFD -> localization fallback gives segment 5.
    # ------------------------------------------------------------
    if case in (4, 5, 6):
        result[8026][0] = 1          # GI DUA HR0 = forced trip
        if case == 4:
            result[8025][0] = 1      # GD05 LBS1 HFD
            result[8024][0] = 1      # GD04 LBS1 HFD
        elif case == 5:
            result[8025][0] = 1      # GD05 LBS1 HFD
        return result

    # ------------------------------------------------------------
    # Source faults.
    # ------------------------------------------------------------
    if case == 7:
        result[8020][1] = 1          # GI SATU HR1 = forced UV
        return result

    if case == 8:
        result[8026][1] = 1          # GI DUA HR1 = forced UV
        return result

    return result


def hr_size(port):
    return 4 if port in GI_PORTS else 5


async def write_register(port: int, address: int, value: int):
    client = AsyncModbusTcpClient(
        HOST,
        port=port,
    )
    try:
        ok = await client.connect()
        if not ok or not client.connected:
            logging.error(
                "RTU :%d tidak dapat dihubungi",
                port,
            )
            return False

        response = await client.write_register(
            address,
            int(value),
            slave=SLAVE,
        )

        if response is None or response.isError():
            logging.error(
                "Write injection :%d HR%d gagal: %s",
                port,
                address,
                response,
            )
            return False

        return True

    except Exception as exc:
        logging.error(
            "Write injection :%d HR%d error: %s",
            port,
            address,
            exc,
        )
        return False

    finally:
        client.close()


async def clear_port_injection(port: int):
    results = await asyncio.gather(
        *(
            write_register(port, address, 0)
            for address in range(hr_size(port))
        ),
        return_exceptions=True,
    )
    return all(result is True for result in results)


async def reset_rtu(port: int):
    client = AsyncModbusTcpClient(
        HOST,
        port=port,
    )

    try:
        ok = await client.connect()
        if not ok or not client.connected:
            logging.error(
                "Reset :%d tidak dapat dihubungi",
                port,
            )
            return False

        response = await client.write_coil(
            T.CO_RESET,
            True,
            slave=SLAVE,
        )

        if response is None or response.isError():
            logging.error(
                "Reset :%d gagal: %s",
                port,
                response,
            )
            return False

        await asyncio.sleep(0.10)

        response = await client.write_coil(
            T.CO_RESET,
            False,
            slave=SLAVE,
        )

        if response is None or response.isError():
            logging.error(
                "Reset-off :%d gagal: %s",
                port,
                response,
            )
            return False

        return True

    except Exception as exc:
        logging.error(
            "Reset :%d error: %s",
            port,
            exc,
        )
        return False

    finally:
        client.close()


async def apply_case(case: int):
    case = int(case)

    if case < 0 or case > 8:
        logging.warning(
            "CASE %d diabaikan; valid 0..8",
            case,
        )
        return

    # Global pause first: every RTU freezes CSV at its current index.
    set_global_state(case)

    # Clear any previous injection state.
    clear_results = await asyncio.gather(
        *(
            clear_port_injection(port)
            for port in RTU_PORTS
        ),
        return_exceptions=True,
    )

    injection = injection_for_case(case)

    writes = []
    for port, registers in injection.items():
        for address, value in registers.items():
            writes.append(
                write_register(
                    port,
                    address,
                    value,
                )
            )

    write_results = await asyncio.gather(
        *writes,
        return_exceptions=True,
    )

    clear_ok = sum(
        result is True
        for result in clear_results
    )
    write_ok = sum(
        result is True
        for result in write_results
    )

    logging.info(
        "CASE %d diterapkan: clear %d/%d RTU, "
        "fault write %d/%d, CSV pause=%s",
        case,
        clear_ok,
        len(RTU_PORTS),
        write_ok,
        len(writes),
        case != 0,
    )

    for port in RTU_PORTS:
        logging.info(
            "  :%d injection=%s",
            port,
            injection[port],
        )


async def repair_all():
    # Release global CSV pause first.
    set_global_state(0)

    clear_results = await asyncio.gather(
        *(
            clear_port_injection(port)
            for port in RTU_PORTS
        ),
        return_exceptions=True,
    )

    reset_results = await asyncio.gather(
        *(
            reset_rtu(port)
            for port in RTU_PORTS
        ),
        return_exceptions=True,
    )

    clear_ok = sum(
        result is True
        for result in clear_results
    )
    reset_ok = sum(
        result is True
        for result in reset_results
    )

    logging.info(
        "REPAIR: clear injection %d/%d RTU, "
        "reset %d/%d RTU, CSV pause=False",
        clear_ok,
        len(RTU_PORTS),
        reset_ok,
        len(RTU_PORTS),
    )


async def watcher(context):
    last_case = None
    last_repair = 0
    last_mode = None

    while True:
        await asyncio.sleep(0.05)

        store = context[SLAVE]
        regs = store.getValues(
            T.HR,
            0,
            count=3,
        )

        case = int(regs[HR_CASE])
        mode = int(regs[HR_MODE])
        repair = int(regs[HR_REPAIR])

        if mode != last_mode:
            logging.info(
                "MODE = %s",
                "MANUAL" if mode == 0 else "ONLINE",
            )
            last_mode = mode

        if case != last_case:
            try:
                await apply_case(case)
                last_case = case
            except Exception as exc:
                logging.exception(
                    "Gagal menerapkan CASE %d; watcher tetap berjalan: %s",
                    case,
                    exc,
                )

        if repair and repair != last_repair:
            try:
                await repair_all()
            except Exception as exc:
                logging.exception(
                    "Gagal menjalankan REPAIR; watcher tetap berjalan: %s",
                    exc,
                )

            store.setValues(
                T.HR,
                HR_REPAIR,
                [0],
            )
            store.setValues(
                T.HR,
                HR_CASE,
                [0],
            )

            last_case = 0

        last_repair = repair if repair else 0


async def main():
    set_global_state(0)

    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(
            0,
            [0] * 5,
        ),
        co=ModbusSequentialDataBlock(
            0,
            [0] * 2,
        ),
        di=ModbusSequentialDataBlock(
            0,
            [0] * 2,
        ),
        ir=ModbusSequentialDataBlock(
            0,
            [0] * 3,
        ),
        zero_mode=True,
    )

    context = ModbusServerContext(
        slaves={SLAVE: store},
        single=False,
    )

    asyncio.create_task(
        watcher(context)
    )

    logging.info("======================================")
    logging.info(
        "SYSTEM BEHAVIOR FINAL berjalan di port %d "
        "(Slave ID: %d)",
        PORT,
        SLAVE,
    )
    logging.info(
        "HR0=CASE, HR1=MODE, HR2=REPAIR"
    )
    logging.info(
        "GI HR=4, GD HR=5; fault aktif -> "
        "CSV seluruh RTU PAUSE",
    )
    logging.info(
        "Cases: 0 normal, 1..6 kabel, "
        "7 GI SATU UV, 8 GI DUA UV",
    )
    logging.info("======================================")

    await StartAsyncTcpServer(
        context=context,
        address=("0.0.0.0", PORT),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.error(
            "System Behavior gagal start: %s",
            exc,
        )
        raise
