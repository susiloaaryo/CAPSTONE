"""RTU Gardu Induk (GI) - final FLISR simulator.

Ports:
    GI1 -> 8020
    GI2 -> 8026

Contract:
    Slave ID = 1, zero_mode=True
    DI0/DI1 = CB double point
    DI2 = CB trip
    DI3 = Under Voltage
    DI4 = Over Voltage
    CO0 = CB command
    CO2 = reset trip
    HR0 = forced trip
    HR1 = forced UV
    HR2 = forced current
    HR3 = forced voltage

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


BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "dummydata1.csv"
STATE_FILE = BASE_DIR / "fault_state.json"

SLAVE_ID = 1

V_NOMINAL = 20_000.0
UV_THRESHOLD_V = 18_000.0
OV_THRESHOLD_V = 22_000.0

CO = 1
DI = 2
HR = 3
IR = 4

DI_CB_OPEN = 0
DI_CB_CLOSE = 1
DI_CB_TRIP = 2
DI_UV = 3
DI_OV = 4

CO_CB_COMMAND = 0
CO_RESET_TRIP = 2

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
        self.port = 8020 if self.gi_number == 1 else 8026

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

        self.store = ModbusSlaveContext(
            co=ModbusSequentialDataBlock(0, [1, 0, 0] + [0] * 5),
            di=ModbusSequentialDataBlock(0, [0, 1, 0, 0, 0]),
            hr=ModbusSequentialDataBlock(0, [0, 0, 0, 0]),
            ir=ModbusSequentialDataBlock(0, [0, 0, 0, 0]),
            zero_mode=True,
        )

        self.context = ModbusServerContext(
            slaves={SLAVE_ID: self.store},
            single=False,
        )

        self._publish_cb(False)
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

    def _publish_cb(self, transit=False):
        if transit:
            bits = [0, 0]
        elif self.cb_closed:
            bits = [0, 1]  # CLOSED = 01
        else:
            bits = [1, 0]  # OPEN = 10
        self.store.setValues(DI, 0, bits)

    def _publish_measurement(self, current, voltage, uv, ov):
        self.store.setValues(
            IR, IR_CURRENT,
            [int(max(0, min(65535, round(current))))],
        )
        self.store.setValues(
            IR, IR_VOLTAGE,
            [int(max(0, min(65535, round(voltage))))],
        )
        self.store.setValues(DI, DI_UV, [int(uv)])
        self.store.setValues(DI, DI_OV, [int(ov)])

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

                    self._publish_measurement(
                        current, voltage, uv, ov
                    )

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
                coils = self.store.getValues(CO, 0, count=3)
                command = int(coils[CO_CB_COMMAND])
                reset = int(coils[CO_RESET_TRIP])

                now = time.monotonic()

                if reset:
                    # Reset hanya melepas latch trip. Bila command CB masih
                    # CLOSE (CO0=1), CB harus benar-benar melakukan reclose.
                    # Ini penting karena fault trip dapat membuka CB secara
                    # internal tanpa mengubah CO0 dari 1 -> 0, sehingga command
                    # CLOSE berikutnya tidak menghasilkan rising/change edge.
                    self.trip_latched = False
                    self.store.setValues(
                        CO, CO_RESET_TRIP, [0]
                    )

                    if (
                        command == 1
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

                self.store.setValues(
                    DI,
                    DI_CB_TRIP,
                    [int(self.trip_latched)],
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
        "RTU [%s] berjalan di port %d (Slave ID: %d)",
        sim.name,
        sim.port,
        SLAVE_ID,
    )
    logging.info(
        "GI HR0=trip paksa, HR1=UV paksa; "
        "fault aktif -> CSV seluruh RTU PAUSE",
    )
    logging.info("DP: CLOSED=01, OPEN=10, TRANSIT=00")
    logging.info("======================================")

    tasks = [
        asyncio.create_task(sim.csv_loop()),
        asyncio.create_task(sim.fault_monitor()),
        asyncio.create_task(sim.control_loop()),
    ]

    try:
        await StartAsyncTcpServer(
            context=sim.context,
            address=("0.0.0.0", sim.port),
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
