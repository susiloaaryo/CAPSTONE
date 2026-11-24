"""System Behavior simulator - FLISR testbench.

HMI is the only writer to this service.
The service shares the PC host IP with the Controller but uses TCP port 503.

192.168.250.2:503:
    HR0 = CASE
    HR1 = MODE
    HR2 = REPAIR
    HR3 = TRIGGER sequence (increment on every HMI fault button click)
    HR4 = APPLIED sequence acknowledgement
    HR5 = STATUS (0 idle, 1 verified, 2 partial, 3 not ready, 4 error)

RTU injection targets use internal logical IDs (not network TCP ports):
    GI logical IDs 8020/8026:
        HR0 forced trip
        HR1 forced UV
        HR2 forced current
        HR3 forced voltage
    GD logical IDs 8021..8025:
        HR0 forced HFD1
        HR1 forced HFD2
        HR2 forced current LBS1
        HR3 forced current LBS2
        HR4 forced voltage
        HR5 selector LBS1 (preserved by injection clear)
        HR6 selector LBS2 (preserved by injection clear)
    GI 8020/8026:
        HR4 selector CB (preserved by injection clear)

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
from fault_scenarios import injection_for_case


HOST = T.HOST_SIMULATOR
PORT = T.PORT_TESTBENCH
SLAVE = T.SLAVE_RTU

HR_CASE = 0
HR_MODE = 1
HR_REPAIR = 2
# HMI increments HR_TRIGGER for every button press, including repeated Kx.
# Testbench writes HR_APPLIED only after latches/pattern are verified.
HR_TRIGGER = 3
HR_APPLIED = 4
HR_STATUS = 5

STATUS_IDLE = 0
STATUS_OK = 1
STATUS_PARTIAL = 2
STATUS_NOT_READY = 3
STATUS_ERROR = 4

# Stable logical RTU IDs retained for case definition and logs. Each ID is
# resolved via topologi.endpoint_logical_id() to a different IP on TCP 502.
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


def set_global_state(case: int, active=None) -> bool:
    payload = {
        "case": int(case),
        "active": int(case) != 0 if active is None else bool(active),
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


def hr_size(port):
    return 4 if port in GI_PORTS else 5


async def write_register(port: int, address: int, value: int):
    # `port` is a legacy logical RTU ID (8020..8026), not a TCP port.
    target_host, target_port = T.endpoint_logical_id(port)
    client = AsyncModbusTcpClient(target_host, port=target_port)
    try:
        ok = await client.connect()
        if not ok or not client.connected:
            logging.error(
                "RTU ID %d (%s:%d) tidak dapat dihubungi",
                port, target_host, target_port,
            )
            return False

        response = await client.write_register(
            address,
            int(value),
            slave=SLAVE,
        )

        if response is None or response.isError():
            logging.error(
                "Write injection RTU-ID %d (%s:%d) HR%d gagal: %s",
                port, target_host, target_port, address, response,
            )
            return False

        return True

    except Exception as exc:
        logging.error(
            "Write injection RTU-ID %d (%s:%d) HR%d error: %s",
            port, target_host, target_port, address, exc,
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
    target_host, target_port = T.endpoint_logical_id(port)
    client = AsyncModbusTcpClient(target_host, port=target_port)

    try:
        ok = await client.connect()
        if not ok or not client.connected:
            logging.error(
                "Reset RTU-ID %d (%s:%d) tidak dapat dihubungi",
                port, target_host, target_port,
            )
            return False

        response = await client.write_coil(
            T.CO_RESET,
            True,
            slave=SLAVE,
        )

        if response is None or response.isError():
            logging.error(
                "Reset RTU-ID %d (%s:%d) gagal: %s",
                port, target_host, target_port, response,
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
                "Reset-off RTU-ID %d (%s:%d) gagal: %s",
                port, target_host, target_port, response,
            )
            return False

        return True

    except Exception as exc:
        logging.error(
            "Reset RTU-ID %d (%s:%d) error: %s",
            port, target_host, target_port, exc,
        )
        return False

    finally:
        client.close()


async def _controller_status():
    """Read controller readiness before a test fault is committed."""
    client = AsyncModbusTcpClient(HOST, port=T.PORT_SHG)
    try:
        ok = await client.connect()
        if not ok or not client.connected:
            return None
        co = await client.read_coils(T.CO_SHG_ENABLE, 1, slave=SLAVE)
        di = await client.read_discrete_inputs(0, T.DI_SHG_INPROGRESS + 1, slave=SLAVE)
        ir = await client.read_input_registers(T.IR_FASE, 1, slave=SLAVE)
        if co is None or co.isError() or di is None or di.isError() or ir is None or ir.isError():
            return None
        return {
            "enabled": bool(co.bits[0]),
            "in_progress": bool(di.bits[T.DI_SHG_INPROGRESS]),
            "phase": int(ir.registers[0]),
        }
    except Exception as exc:
        logging.error("Gagal membaca readiness controller: %s", exc)
        return None
    finally:
        client.close()


async def _set_controller_enabled(enabled: bool) -> bool:
    client = AsyncModbusTcpClient(HOST, port=T.PORT_SHG)
    try:
        ok = await client.connect()
        if not ok or not client.connected:
            return False
        response = await client.write_coil(T.CO_SHG_ENABLE, bool(enabled), slave=SLAVE)
        return response is not None and not response.isError()
    except Exception as exc:
        logging.error("Gagal set SHG enable=%s: %s", enabled, exc)
        return False
    finally:
        client.close()


async def _read_rtu_di(port: int):
    target_host, target_port = T.endpoint_logical_id(port)
    client = AsyncModbusTcpClient(target_host, port=target_port)
    try:
        ok = await client.connect()
        if not ok or not client.connected:
            return None
        count = T.JUMLAH_DI_GI if port in GI_PORTS else T.JUMLAH_DI_GD
        response = await client.read_coils(0, count, slave=SLAVE)
        if response is None or response.isError() or len(response.bits) < count:
            return None
        return list(response.bits[:count])
    except Exception as exc:
        logging.debug("Readback FC01 RTU %d gagal: %s", port, exc)
        return None
    finally:
        client.close()


async def _verify_case_pattern(case: int, injection: dict):
    """Verify actual FC01 coil-status feedback, not just successful HR writes."""
    issues = []
    reads = await asyncio.gather(*(_read_rtu_di(port) for port in RTU_PORTS))
    actual_by_port = dict(zip(RTU_PORTS, reads))
    for port in RTU_PORTS:
        bits = actual_by_port[port]
        if bits is None:
            issues.append(f"RTU {port}: tidak dapat membaca FC01")
            continue
        expected = injection.get(port, {})
        if port in GD_PORTS:
            exp_hfd1 = int(bool(expected.get(0, 0)))
            exp_hfd2 = int(bool(expected.get(1, 0)))
            actual_hfd1 = int(bool(bits[T.DI_GD_LBS1_HFD]))
            actual_hfd2 = int(bool(bits[T.DI_GD_LBS2_HFD]))
            if (actual_hfd1, actual_hfd2) != (exp_hfd1, exp_hfd2):
                issues.append(
                    f"RTU {port}: HFD aktual {actual_hfd1}/{actual_hfd2}, "
                    f"target {exp_hfd1}/{exp_hfd2}"
                )
        else:
            exp_trip = int(bool(expected.get(0, 0)))
            actual_trip = int(bool(bits[T.DI_CB_TRIP]))
            if actual_trip != exp_trip:
                issues.append(f"RTU {port}: Trip aktual {actual_trip}, target {exp_trip}")
            if case in (7, 8):
                exp_uv = int(bool(expected.get(1, 0)))
                actual_uv = int(bool(bits[T.DI_UV_GI]))
                if actual_uv != exp_uv:
                    issues.append(f"RTU {port}: UV aktual {actual_uv}, target {exp_uv}")
    return not issues, issues


def publish_testbench_points(store, case: int, status: int):
    """Publish CASE result to EBC M30_TestBench FC01 points CS0..CS7.

    M30_TestBench polls ten coils at .2:503 with Unit ID 30.  The supplied
    CoreDB status map exposes CS0..CS7: K1..K6 occupy bits 0..5; source-loss
    cases K7/K8 occupy bits 6/7.  Bits 8/9 remain reserved at zero.
    """
    bits = [0] * 10
    if status == STATUS_OK:
        if 1 <= int(case) <= 6:
            bits[int(case) - 1] = 1
        elif int(case) == 7:
            bits[6] = 1
        elif int(case) == 8:
            bits[7] = 1
    store.setValues(T.CO, 0, bits)


async def apply_case(case: int, sequence: int, store):
    """Apply a fault as a transaction so Controller never sees partial HFD.

    The testbench: checks controller readiness, temporarily disables SHG,
    clears injections, waits for each RTU scanner to see the low level, resets
    protection latches, writes the complete new pattern, verifies RTU DI
    feedback, acknowledges the sequence, then restores the prior SHG enable.
    """
    case = int(case)
    sequence = int(sequence)
    status = STATUS_ERROR
    previous_enabled = None
    controller_paused = False

    def acknowledge(result_status):
        store.setValues(T.HR, HR_STATUS, [int(result_status)])
        store.setValues(T.HR, HR_APPLIED, [sequence])
        publish_testbench_points(store, case, int(result_status))

    if case < 0 or case > 8:
        logging.warning("CASE %d diabaikan; valid 0..8", case)
        acknowledge(STATUS_ERROR)
        return

    readiness = await _controller_status()
    if readiness is None:
        logging.error("CASE %d tidak diterapkan: controller tidak bisa dibaca", case)
        acknowledge(STATUS_ERROR)
        return
    previous_enabled = readiness["enabled"]
    if case != 0 and (
        not readiness["enabled"]
        or readiness["in_progress"]
        or readiness["phase"] != T.SIAGA
    ):
        logging.warning(
            "CASE %d ditolak: SHG harus ENABLE, tidak in-progress, dan fase SIAGA "
            "(enabled=%s, in_progress=%s, phase=%s). Gunakan RESET SISTEM dan tunggu SIAGA.",
            case, readiness["enabled"], readiness["in_progress"], readiness["phase"],
        )
        acknowledge(STATUS_NOT_READY)
        return

    if previous_enabled:
        controller_paused = await _set_controller_enabled(False)
        if not controller_paused:
            logging.error("CASE %d dibatalkan: gagal menahan Controller saat menyusun HFD", case)
            acknowledge(STATUS_ERROR)
            return

    try:
        # Keep CSV frozen while injection levels and old protection latches reset.
        set_global_state(case if case else 0, active=True)

        clear_results = await asyncio.gather(
            *(clear_port_injection(port) for port in RTU_PORTS),
            return_exceptions=True,
        )
        clear_ok = all(result is True for result in clear_results)
        # fault_monitor runs every 50 ms. Ensure it observes HR0/HR1=0 and
        # clears its remembered edge state before a repeated case writes 1 again.
        await asyncio.sleep(0.18)

        reset_results = await asyncio.gather(
            *(reset_rtu(port) for port in RTU_PORTS),
            return_exceptions=True,
        )
        reset_ok = all(result is True for result in reset_results)
        await asyncio.sleep(0.18)

        if not clear_ok or not reset_ok:
            logging.error(
                "CASE %d dibatalkan: clear injections %d/%d, reset protection %d/%d",
                case,
                sum(result is True for result in clear_results), len(RTU_PORTS),
                sum(result is True for result in reset_results), len(RTU_PORTS),
            )
            set_global_state(0, active=False)
            status = STATUS_PARTIAL
            acknowledge(status)
            return

        injection = injection_for_case(case)
        writes = [
            write_register(port, address, value)
            for port, registers in injection.items()
            for address, value in registers.items()
        ]
        write_results = await asyncio.gather(*writes, return_exceptions=True)
        write_ok = all(result is True for result in write_results)

        # Let the 50 ms protection tasks latch the new pattern before Controller
        # is re-enabled. This is what removes the intermittent partial HFD map.
        await asyncio.sleep(0.20)
        verified, issues = await _verify_case_pattern(case, injection)
        logging.info(
            "CASE %d seq=%d: clear %d/%d, reset %d/%d, writes %d/%d, verified=%s, CSV pause=%s",
            case, sequence,
            sum(result is True for result in clear_results), len(RTU_PORTS),
            sum(result is True for result in reset_results), len(RTU_PORTS),
            sum(result is True for result in write_results), len(writes),
            verified, case != 0,
        )
        for port in RTU_PORTS:
            logging.info("  RTU-ID %d injection=%s", port, injection[port])
        if issues:
            for issue in issues:
                logging.error("  Pattern verify: %s", issue)

        if not write_ok or not verified:
            # Never re-enable SHG on a partial HFD pattern: clear it, reset
            # the protection latches again, and return to safe normal state.
            await asyncio.gather(
                *(clear_port_injection(port) for port in RTU_PORTS),
                return_exceptions=True,
            )
            await asyncio.sleep(0.18)
            await asyncio.gather(
                *(reset_rtu(port) for port in RTU_PORTS),
                return_exceptions=True,
            )
            await asyncio.sleep(0.18)
            set_global_state(0, active=False)
            acknowledge(STATUS_PARTIAL)
            return

        # Case 0 means clear and resume CSV; active cases keep it frozen.
        set_global_state(case, active=(case != 0))
        acknowledge(STATUS_OK)
    except Exception as exc:
        logging.exception("Gagal menerapkan CASE %d: %s", case, exc)
        set_global_state(0, active=False)
        acknowledge(STATUS_ERROR)
    finally:
        if previous_enabled and controller_paused:
            if not await _set_controller_enabled(True):
                logging.error("SHG gagal di-enable kembali setelah CASE %d", case)


async def repair_all():
    # Keep CSV frozen until stale injections and latches are cleared.
    set_global_state(0, active=True)

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

    set_global_state(0, active=False)
    logging.info(
        "REPAIR: clear injection %d/%d RTU, "
        "reset %d/%d RTU, CSV pause=False",
        clear_ok,
        len(RTU_PORTS),
        reset_ok,
        len(RTU_PORTS),
    )


async def watcher(context):
    last_trigger = 0
    last_repair = 0
    last_mode = None

    while True:
        await asyncio.sleep(0.05)
        store = context[SLAVE]
        regs = store.getValues(T.HR, 0, count=6)
        case = int(regs[HR_CASE])
        mode = int(regs[HR_MODE])
        repair = int(regs[HR_REPAIR])
        trigger = int(regs[HR_TRIGGER])

        if mode != last_mode:
            logging.info("MODE = %s", "MANUAL" if mode == 0 else "ONLINE")
            last_mode = mode

        # Trigger counter, not case value, lets the same K button run again.
        if trigger != last_trigger:
            try:
                await apply_case(case, trigger, store)
            except Exception as exc:
                logging.exception("Gagal menerapkan CASE %d seq=%d: %s", case, trigger, exc)
                store.setValues(T.HR, HR_STATUS, [STATUS_ERROR])
                store.setValues(T.HR, HR_APPLIED, [trigger])
                publish_testbench_points(store, case, STATUS_ERROR)
            last_trigger = trigger

        if repair and repair != last_repair:
            try:
                await repair_all()
                store.setValues(T.HR, HR_STATUS, [STATUS_OK])
                publish_testbench_points(store, 0, STATUS_OK)
            except Exception as exc:
                logging.exception("Gagal menjalankan REPAIR; watcher tetap berjalan: %s", exc)
                store.setValues(T.HR, HR_STATUS, [STATUS_ERROR])
                publish_testbench_points(store, 0, STATUS_ERROR)

            store.setValues(T.HR, HR_REPAIR, [0])
            store.setValues(T.HR, HR_CASE, [0])
            # Acknowledge the current sequence so HMI does not wait on an old request.
            current_trigger = int(store.getValues(T.HR, HR_TRIGGER, count=1)[0])
            store.setValues(T.HR, HR_APPLIED, [current_trigger])
            last_trigger = current_trigger

        last_repair = repair if repair else 0


async def main():
    set_global_state(0)

    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(
            0,
            [0] * 6,
        ),
        co=ModbusSequentialDataBlock(
            0,
            [0] * 10,
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
        # Unit ID 1 is retained for local tooling; EBC M30_TestBench polls 30.
        slaves={SLAVE: store, T.TESTBENCH_EBC_UNIT_ID: store},
        single=False,
    )

    asyncio.create_task(
        watcher(context)
    )

    logging.info("======================================")
    logging.info(
        "SYSTEM BEHAVIOR berjalan di %s:%d (Unit ID lokal=%d, EBC=%d)",
        HOST, PORT, SLAVE, T.TESTBENCH_EBC_UNIT_ID,
    )
    logging.info(
        "HR0=CASE, HR1=MODE, HR2=REPAIR, HR3=TRIGGER, HR4=APPLIED, HR5=STATUS"
    )
    logging.info(
        "GI HR=4, GD HR=5; fault aktif -> "
        "CSV seluruh RTU PAUSE",
    )
    logging.info(
        "Cases: 0 normal, 1..6 kabel, 7 GI SATU UV, 8 GI DUA UV; "
        "EBC FC01 CS0..7 = K1..K8",
    )
    logging.info("======================================")

    await StartAsyncTcpServer(
        context=context,
        address=(HOST, PORT),
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
