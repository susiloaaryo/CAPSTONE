"""RTU Gardu Induk (GI) - final FLISR simulator.

Endpoints (Modbus TCP 502):
    GI1 / GI SATU -> 192.168.250.3
    GI2 / GI DUA  -> 192.168.250.4

Contract:
    Slave ID = 1, zero_mode=True
    FC01 CO0..5 mirrors EBC CoreDb CS0..5:
      CBTR, CB CLOSE, CB OPEN, LR LOCAL, LR REMOTE, UV
    CO10=CB level command; CO12=reset trip
    EBC FC05 writes at CS1/CS2 are momentary CLOSE/OPEN. The supplied CoreDb
    has no SOURCE_COORD for GI trip reset; FC05 destination CS0 is intercepted
    only if a reset mapping is later added in Easergy Builder.
    HR0=forced trip; HR1=forced UV; HR2=forced current; HR3=forced voltage
    HR4=CB selector (0=LOCAL, 1=REMOTE; defaults REMOTE)

Multi-master / multi-client behavior:
    One shared datastore is served by a single Modbus TCP server on this RTU IP.
    Multiple TCP clients may connect concurrently. Unit ID 1 is retained for
    direct mode/testbench; the additional EBC Mdbm Unit ID comes from topologi.py.
    In mode Y, EBC FC05 command writes are translated into events without
    overwriting the FC01 status image.

Simulator-only coordination:
    fault_state.json is used only to pause/resume CSV progression on
    all seven RTUs while a test fault is active. It does not change
    the documented Modbus contract.
"""

import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

import topologi as T
from rtu_command_datablock import EBCCommandCoilDataBlock


BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "dummydata1.csv"
STATE_FILE = BASE_DIR / "fault_state.json"

SLAVE_ID = 1

V_NOMINAL = 20_000.0
UV_THRESHOLD_V = 18_000.0
OV_THRESHOLD_V = 22_000.0

CO = 1
# FC01 status image in CO0..CO5; command coils are kept separate.
CO_STATUS = 1
HR = 3
IR = 4

# FC01 image aligned with EBC M1_GIA / M7_GIB and S1_GIA / S7_GIB CS:0..5.
CO_CB_TRIP = 0
CO_CB_CLOSE = 1
CO_CB_OPEN = 2
CO_CB_LOCAL = 3
CO_CB_REMOTE = 4
CO_UV = 5

CO_CB_COMMAND = 10
CO_RESET_TRIP = 12
HR_SELECTOR_CB = 4  # 0=LOCAL, 1=REMOTE

IR_CURRENT = 0
IR_VOLTAGE = 2

TRANSIT_S = 0.20
CSV_STEP_S = 1.0
CONTROL_STEP_S = 0.05

logging.basicConfig(
    format="%(levelname)s: %(message)s",
    level=logging.INFO,
)


def normalisasi_lokasi(value):
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def filter_gi(df, gi_number):
    lokasi = df["Lokasi"].fillna("").map(normalisasi_lokasi)
    return df.loc[lokasi == f"GI{int(gi_number)}"].copy()


def angka(row, kolom, default=0.0):
    if kolom not in row:
        return default
    value = pd.to_numeric(row[kolom], errors="coerce")
    return default if pd.isna(value) else float(value)


class GISimulator:
    def __init__(self, gi_number):
        self.gi_number = int(gi_number)
        self.name = f"GI0{self.gi_number}"
        self.node_index = T.GI_KIRI if self.gi_number == 1 else T.GI_KANAN
        self.port = T.port_node(self.node_index)

        if not CSV_FILE.exists():
            raise FileNotFoundError(f"CSV tidak ditemukan: {CSV_FILE}")

        df = pd.read_csv(CSV_FILE)
        required = {"Lokasi", "Timestamp", "VL (V)", "IL (A)"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(f"Kolom CSV wajib tidak ada: {missing}")

        self.df = filter_gi(df, self.gi_number)
        if self.df.empty:
            raise ValueError(f"Data untuk {self.name} tidak ditemukan di CSV")

        self.df = self.df.copy()
        self.df["_ts"] = pd.to_datetime(self.df["Timestamp"], errors="coerce")
        self.df = self.df.sort_values(["_ts", "Timestamp"], kind="stable")

        self.csv_index = 0

        self.trip_latched = False
        self._prev_force_trip = False
        self.cb_closed = True
        self.command_cb = 1
        self.last_command_cb = 1

        self.transition_target = None
        self.transition_end = 0.0

        ebc_command_map = {
            0: ("reset_trip", 0),
            1: ("switch", 0, True),
            2: ("switch", 0, False),
        }
        self.coil_block = EBCCommandCoilDataBlock(
            0, [0, 1, 0, 0, 1, 0] + [0] * 4 + [1, 0, 0],
            ebc_command_map,
        )
        self.store = ModbusSlaveContext(
            co=self.coil_block,
            di=ModbusSequentialDataBlock(0, [0, 1, 0, 0, 1, 0]),
            # HR0..HR3 injection; HR4=CB selector (0=LOCAL, 1=REMOTE).
            hr=ModbusSequentialDataBlock(0, [0, 0, 0, 0, 1]),
            ir=ModbusSequentialDataBlock(0, [0, 0, 0, 0]),
            zero_mode=True,
        )

        downstream_unit_id = T.mdbm_unit_id(self.node_index)
        slave_contexts = {
            unit_id: self.store
            for unit_id in sorted({SLAVE_ID, downstream_unit_id})
        }
        self.context = ModbusServerContext(
            slaves=slave_contexts,
            single=False,
        )

        self._publish_cb(False)
        self._publish_selector_status()
        self._publish_measurement(0.0, V_NOMINAL, 0, 0)

    def global_pause(self):
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return bool(state.get("active", False))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return False

    def read_injection(self):
        hr = self.store.getValues(HR, 0, count=4)
        return (
            bool(hr[0]),
            bool(hr[1]),
            float(hr[2]) if hr[2] > 0 else None,
            float(hr[3]) if hr[3] > 0 else None,
        )

    def local_fault_active(self):
        force_trip, force_uv, _, _ = self.read_injection()
        return force_trip or force_uv

    def csv_paused(self):
        return self.global_pause()

    def _publish_selector_status(self):
        """Publish selector feedback; invalid HR values publish neither bit."""
        mode = int(self.store.getValues(HR, HR_SELECTOR_CB, count=1)[0])
        self.coil_block.set_internal(CO_CB_LOCAL, [int(mode == 0)])
        self.coil_block.set_internal(CO_CB_REMOTE, [int(mode == 1)])

    def _publish_cb(self, transit=False):
        if transit:
            bits = [0, 0]
        elif self.cb_closed:
            bits = [0, 1]  # CLOSED = 01
        else:
            bits = [1, 0]  # OPEN = 10
        self.coil_block.set_internal(CO_CB_CLOSE, [bits[1]])
        self.coil_block.set_internal(CO_CB_OPEN, [bits[0]])
        self.coil_block.set_internal(CO_CB_TRIP, [int(self.trip_latched)])

    def _publish_measurement(self, current, voltage, uv, ov):
        self.store.setValues(
            IR, IR_CURRENT,
            [int(max(0, min(65535, round(current))))],
        )
        self.store.setValues(
            IR, IR_VOLTAGE,
            [int(max(0, min(65535, round(voltage))))],
        )
        self.coil_block.set_internal(CO_UV, [int(uv)])

    async def csv_loop(self):
        logging.info("CSV cocok untuk %s: %d baris", self.name, len(self.df))

        while self.csv_index < len(self.df):
            if self.csv_paused():
                await asyncio.sleep(CONTROL_STEP_S)
                continue

            row = self.df.iloc[self.csv_index]

            voltage = angka(row, "VL (V)", V_NOMINAL)
            current = angka(row, "IL (A)", 0.0)

            uv = int(voltage < UV_THRESHOLD_V)
            ov = int(voltage > OV_THRESHOLD_V)

            # CSV adalah telemetri. Fault test berasal dari injection
            # HR0/HR1, bukan dari puncak arus normal dataset.
            self._publish_measurement(current, voltage, uv, ov)

            logging.info(
                "[%s] CSV idx=%d -> UV:%d OV:%d CB:%s I:%.2f V:%.2f",
                row.get("Timestamp", "?"),
                self.csv_index,
                uv,
                ov,
                "CLOSE" if self.cb_closed else "OPEN",
                current,
                voltage,
            )

            self.csv_index += 1

            for _ in range(20):
                if self.csv_paused():
                    break
                await asyncio.sleep(CSV_STEP_S / 20)

        logging.info(
            "CSV %s selesai; simulator tetap melayani Modbus.",
            self.name,
        )

    async def fault_monitor(self):
        last_active = False

        try:
            while True:
                force_trip, force_uv, forced_current, forced_voltage = (
                    self.read_injection()
                )
                active = force_trip or force_uv

                # HR0 is a trigger, not a continuously re-latching level.
                # After the controller resets the GI trip during healing,
                # the same test case may remain active in the testbench
                # (CSV is still paused) without immediately tripping again.
                if force_trip and not self._prev_force_trip and not self.trip_latched:
                    self.trip_latched = True
                    self.cb_closed = False
                    self.transition_target = None
                    self._publish_cb(False)
                    logging.warning(
                        "[%s] FORCED TRIP aktif (HR0 rising edge)",
                        self.name,
                    )

                if active:
                    # Publish injected protection telemetry for BOTH trip and
                    # UV cases. Previously a UV-only case (HR1=1, HR0=0) did
                    # UV is published directly at EBC CS:5
                    # rising-edge branch.
                    voltage = (
                        forced_voltage
                        if forced_voltage is not None
                        else V_NOMINAL
                    )
                    current = (
                        forced_current
                        if forced_current is not None
                        else 0.0
                    )
                    uv = int(force_uv)
                    ov = int(voltage > OV_THRESHOLD_V)
                    self._publish_measurement(current, voltage, uv, ov)
                elif last_active:
                    # Clear forced indication immediately; CSV resumes
                    # separately from the frozen index.
                    self._publish_measurement(0.0, V_NOMINAL, 0, 0)
                    logging.info(
                        "[%s] Fault injection cleared; CSV resume idx=%d",
                        self.name,
                        self.csv_index,
                    )

                last_active = active
                self._prev_force_trip = force_trip
                await asyncio.sleep(CONTROL_STEP_S)

        except asyncio.CancelledError:
            raise

    async def control_loop(self):
        try:
            while True:
                coils = self.store.getValues(CO, 10, count=3)
                command = int(coils[0])
                reset = int(coils[2])
                selector_mode = int(self.store.getValues(HR, HR_SELECTOR_CB, count=1)[0])
                self._publish_selector_status()

                now = time.monotonic()
                for event in self.coil_block.pop_events():
                    if event[0] == "reset_trip":
                        self.trip_latched = False
                        logging.info("[%s] EBC reset trip diterima (FC05 CS:0).", self.name)
                        if (
                            selector_mode == 1
                            and command == 1
                            and not self.cb_closed
                            and self.transition_target is None
                        ):
                            self.command_cb = 1
                            self.last_command_cb = 1
                            self.transition_target = 1
                            self.transition_end = now + TRANSIT_S
                            self._publish_cb(True)
                    elif event[0] == "switch":
                        _, _bay, target = event
                        target = int(bool(target))
                        if selector_mode == 1 and self.transition_target is None:
                            self.last_command_cb = target
                            self.command_cb = target
                            self.coil_block.set_internal(10, [target])
                            if int(self.cb_closed) != target:
                                self.transition_target = target
                                self.transition_end = now + TRANSIT_S
                                self._publish_cb(True)
                            logging.info(
                                "[%s] EBC CB command -> %s",
                                self.name, "CLOSE" if target else "OPEN",
                            )
                        else:
                            logging.warning(
                                "[%s] EBC CB command ditolak: selector bukan REMOTE atau CB sedang transit",
                                self.name,
                            )

                if reset:
                    # Reset hanya melepas latch trip. Bila command CB masih
                    # CLOSE (CO0=1), CB harus benar-benar melakukan reclose.
                    # Ini penting karena fault trip dapat membuka CB secara
                    # internal tanpa mengubah CO0 dari 1 -> 0, sehingga command
                    # CLOSE berikutnya tidak menghasilkan rising/change edge.
                    self.trip_latched = False
                    self.coil_block.set_internal(CO_RESET_TRIP, [0])

                    if (
                        selector_mode == 1
                        and command == 1
                        and not self.cb_closed
                        and self.transition_target is None
                    ):
                        self.command_cb = 1
                        self.last_command_cb = 1
                        self.transition_target = 1
                        self.transition_end = now + TRANSIT_S
                        self._publish_cb(True)
                        logging.info(
                            "[%s] Reset trip + command CLOSE -> CB reclose, transit %.0f ms",
                            self.name,
                            TRANSIT_S * 1000,
                        )

                    logging.info(
                        "[%s] Reset trip diterima.",
                        self.name,
                    )

                if selector_mode == 1:
                    if (
                        command != self.last_command_cb
                        and self.transition_target is None
                    ):
                        self.last_command_cb = command
                        self.command_cb = command
                        self.transition_target = command
                        self.transition_end = now + TRANSIT_S
                        self._publish_cb(True)
                        logging.info(
                            "[%s] CB command -> %s, transit 200 ms",
                            self.name,
                            "CLOSE" if command else "OPEN",
                        )
                else:
                    # Consume remote commands while LOCAL/invalid so they do
                    # not unexpectedly execute if selector later returns REMOTE.
                    if command != self.last_command_cb:
                        logging.warning(
                            "[%s] Remote CB command ditolak: selector bukan REMOTE",
                            self.name,
                        )
                    self.last_command_cb = command

                if (
                    self.transition_target is not None
                    and now >= self.transition_end
                ):
                    target = int(self.transition_target)
                    self.transition_target = None
                    self.cb_closed = bool(
                        target == 1 and not self.trip_latched
                    )
                    self._publish_cb(False)

                if self.trip_latched and self.cb_closed:
                    self.cb_closed = False
                    self._publish_cb(False)

                self.coil_block.set_internal(
                    CO_CB_TRIP, [int(self.trip_latched)]
                )

                await asyncio.sleep(CONTROL_STEP_S)

        except asyncio.CancelledError:
            raise


async def run_rtu(gi_number):
    if int(gi_number) not in (1, 2):
        raise ValueError("Nomor GI harus 1 atau 2")

    sim = GISimulator(int(gi_number))

    logging.info("======================================")
    logging.info(
        "RTU [%s] berjalan di %s:%d (Unit ID aktif: %s)",
        sim.name,
        T.ip_node(sim.node_index),
        sim.port,
        sorted({SLAVE_ID, T.mdbm_unit_id(sim.node_index)}),
    )
    logging.info(
        "GI HR0=trip paksa, HR1=UV paksa; "
        "fault aktif -> CSV seluruh RTU PAUSE",
    )
    logging.info("DP: CLOSED=01, OPEN=10, TRANSIT=00")
    logging.info(
        "Multi-client ready: direct/testbench Unit ID 1 + EBC Mdbm Unit ID "
        f"{T.mdbm_unit_id(sim.node_index)}; FC01 status / FC05 EBC commands."
    )
    logging.info("======================================")

    tasks = [
        asyncio.create_task(sim.csv_loop()),
        asyncio.create_task(sim.fault_monitor()),
        asyncio.create_task(sim.control_loop()),
    ]

    try:
        await StartAsyncTcpServer(
            context=sim.context,
            address=(T.ip_node(sim.node_index), sim.port),
        )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: py rtu_gi.py 1|2")
        sys.exit(1)

    try:
        asyncio.run(run_rtu(int(sys.argv[1])))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.error("RTU GI gagal start: %s", exc)
        sys.exit(1)
