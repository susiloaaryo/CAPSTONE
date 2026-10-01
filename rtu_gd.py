"""RTU Gardu Distribusi (GD) - final FLISR simulator.

Ports:
    GD01 -> 8021 ... GD05 -> 8025

Contract:
    Slave ID = 1, zero_mode=True
    DI0/1  = LBS1 DP
    DI2    = HFD1
    DI4/5  = LBS2 DP
    DI6    = HFD2
    DI8    = UV
    DI9    = OV
    CO0    = LBS1 command
    CO1    = LBS2 command
    CO2    = reset HFD
    HR0    = forced HFD1
    HR1    = forced HFD2
    HR2    = forced current LBS1
    HR3    = forced current LBS2
    HR4    = forced voltage

Simulator-only coordination:
    fault_state.json pauses CSV progression on every RTU while a test
    fault is active. It does not change the documented Modbus contract.
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

DI_LBS1_OPEN = 0
DI_LBS1_CLOSE = 1
DI_HFD1 = 2
DI_LBS2_OPEN = 4
DI_LBS2_CLOSE = 5
DI_HFD2 = 6
DI_UV = 8
DI_OV = 9

CO_LBS1 = 0
CO_LBS2 = 1
CO_RESET_HFD = 2

IR_CURRENT_LBS1 = 0
IR_CURRENT_LBS2 = 1
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


def filter_gd(df, gd_number):
    lokasi = df["Lokasi"].fillna("").map(normalisasi_lokasi)
    return df.loc[
        lokasi == f"GD{int(gd_number):02d}"
    ].copy()


def angka(row, col, default=0.0):
    if col not in row:
        return default
    value = pd.to_numeric(row[col], errors="coerce")
    return default if pd.isna(value) else float(value)


class GDSimulator:
    def __init__(self, gd_number):
        self.gd_number = int(gd_number)
        self.name = f"GD0{self.gd_number}"
        self.port = 8020 + self.gd_number

        if not CSV_FILE.exists():
            raise FileNotFoundError(
                f"CSV tidak ditemukan: {CSV_FILE}"
            )

        df = pd.read_csv(CSV_FILE)
        required = {"Lokasi", "Timestamp"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(
                f"Kolom CSV wajib tidak ada: {missing}"
            )

        self.df = filter_gd(df, self.gd_number)
        if self.df.empty:
            raise ValueError(
                f"Data untuk {self.name} tidak ditemukan di CSV"
            )

        self.df = self.df.copy()
        self.df["_ts"] = pd.to_datetime(
            self.df["Timestamp"],
            errors="coerce",
        )
        self.df = self.df.sort_values(
            ["_ts", "Timestamp"],
            kind="stable",
        )

        self.csv_index = 0

        self.lbs1_closed = True
        self.lbs2_closed = False if self.gd_number == 3 else True

        self.last_cmd_lbs1 = 1
        self.last_cmd_lbs2 = (
            0 if self.gd_number == 3 else 1
        )

        self.transit_lbs1 = None
        self.transit_lbs2 = None
        self.transit_end_lbs1 = 0.0
        self.transit_end_lbs2 = 0.0

        self.hfd1_latched = False
        self.hfd2_latched = False
        self._prev_hfd1 = False
        self._prev_hfd2 = False

        self.store = ModbusSlaveContext(
            co=ModbusSequentialDataBlock(
                0,
                [
                    self.last_cmd_lbs1,
                    self.last_cmd_lbs2,
                    0,
                ] + [0] * 7,
            ),
            di=ModbusSequentialDataBlock(
                0, [0] * 10
            ),
            hr=ModbusSequentialDataBlock(
                0, [0] * 5
            ),
            ir=ModbusSequentialDataBlock(
                0, [0] * 4
            ),
            zero_mode=True,
        )

        self.context = ModbusServerContext(
            slaves={SLAVE_ID: self.store},
            single=False,
        )

        self._publish_positions(False, False)
        self._publish_measurement(
            0.0, 0.0, V_NOMINAL, 0, 0
        )

    def global_pause(self):
        try:
            state = json.loads(
                STATE_FILE.read_text(encoding="utf-8")
            )
            return bool(state.get("active", False))
        except (
            FileNotFoundError,
            OSError,
            ValueError,
            TypeError,
        ):
            return False

    def _read_injection(self):
        hr = self.store.getValues(HR, 0, count=5)
        return {
            "hfd1": bool(hr[0]),
            "hfd2": bool(hr[1]),
            "i1": float(hr[2]) if hr[2] > 0 else None,
            "i2": float(hr[3]) if hr[3] > 0 else None,
            "v": float(hr[4]) if hr[4] > 0 else None,
        }

    def local_fault_active(self):
        inj = self._read_injection()
        return inj["hfd1"] or inj["hfd2"]

    def csv_paused(self):
        return self.global_pause()

    def _publish_positions(
        self,
        transit1=False,
        transit2=False,
    ):
        if transit1:
            b1 = [0, 0]
        elif self.lbs1_closed:
            b1 = [0, 1]
        else:
            b1 = [1, 0]

        if transit2:
            b2 = [0, 0]
        elif self.lbs2_closed:
            b2 = [0, 1]
        else:
            b2 = [1, 0]

        self.store.setValues(
            DI, DI_LBS1_OPEN, b1
        )
        self.store.setValues(
            DI, DI_LBS2_OPEN, b2
        )

    def _publish_measurement(
        self,
        current1,
        current2,
        voltage,
        uv,
        ov,
    ):
        self.store.setValues(
            IR,
            IR_CURRENT_LBS1,
            [int(max(0, min(65535, round(current1))))],
        )
        self.store.setValues(
            IR,
            IR_CURRENT_LBS2,
            [int(max(0, min(65535, round(current2))))],
        )
        self.store.setValues(
            IR,
            IR_VOLTAGE,
            [int(max(0, min(65535, round(voltage))))],
        )
        self.store.setValues(
            DI, DI_UV, [int(uv)]
        )
        self.store.setValues(
            DI, DI_OV, [int(ov)]
        )

    async def csv_loop(self):
        logging.info(
            "CSV cocok untuk %s: %d baris",
            self.name,
            len(self.df),
        )

        while self.csv_index < len(self.df):
            if self.csv_paused():
                await asyncio.sleep(CONTROL_STEP_S)
                continue

            row = self.df.iloc[self.csv_index]
            voltage = angka(
                row, "VL (V)", V_NOMINAL
            )

            i1 = angka(
                row,
                "IL1 (A)",
                angka(row, "IL (A)", 0.0),
            )
            i2 = angka(
                row,
                "IL2 (A)",
                angka(row, "IL (A)", 0.0),
            )

            uv = int(voltage < UV_THRESHOLD_V)
            ov = int(voltage > OV_THRESHOLD_V)

            # HFD berasal dari fault injection, bukan dari
            # arus normal CSV.
            self._publish_measurement(
                i1, i2, voltage, uv, ov
            )

            logging.info(
                "[%s] CSV idx=%d -> UV:%d OV:%d "
                "HFD:%d/%d LBS1:%s LBS2:%s",
                row.get("Timestamp", "?"),
                self.csv_index,
                uv,
                ov,
                int(self.hfd1_latched),
                int(self.hfd2_latched),
                "CLOSE"
                if self.lbs1_closed
                else "OPEN",
                "CLOSE"
                if self.lbs2_closed
                else "OPEN",
            )

            self.csv_index += 1

            for _ in range(20):
                if self.csv_paused():
                    break
                await asyncio.sleep(
                    CSV_STEP_S / 20
                )

        logging.info(
            "CSV %s selesai; simulator tetap "
            "melayani Modbus.",
            self.name,
        )

    async def fault_monitor(self):
        last_active = False

        try:
            while True:
                inj = self._read_injection()
                active = (
                    inj["hfd1"] or inj["hfd2"]
                )

                # HR0/HR1 are fault triggers. Use rising edges so a reset
                # from the controller clears the protection latch while
                # the testbench can keep the case active / CSV paused.
                if inj["hfd1"] and not self._prev_hfd1 and not self.hfd1_latched:
                    logging.warning(
                        "[%s] FORCED HFD1 aktif (HR0 rising edge)",
                        self.name,
                    )
                    self.hfd1_latched = True

                if inj["hfd2"] and not self._prev_hfd2 and not self.hfd2_latched:
                    logging.warning(
                        "[%s] FORCED HFD2 aktif (HR1 rising edge)",
                        self.name,
                    )
                    self.hfd2_latched = True

                if not active and last_active:
                    logging.info(
                        "[%s] Fault injection cleared; "
                        "CSV resume idx=%d",
                        self.name,
                        self.csv_index,
                    )

                # Publish HFD independently of CSV.
                self.store.setValues(
                    DI,
                    DI_HFD1,
                    [int(self.hfd1_latched)],
                )
                self.store.setValues(
                    DI,
                    DI_HFD2,
                    [int(self.hfd2_latched)],
                )

                last_active = active
                self._prev_hfd1 = inj["hfd1"]
                self._prev_hfd2 = inj["hfd2"]
                await asyncio.sleep(CONTROL_STEP_S)

        except asyncio.CancelledError:
            raise

    async def control_loop(self):
        try:
            while True:
                coils = self.store.getValues(
                    CO, 0, count=3
                )

                cmd1 = int(coils[CO_LBS1])
                cmd2 = int(coils[CO_LBS2])
                reset = int(coils[CO_RESET_HFD])

                if reset:
                    self.hfd1_latched = False
                    self.hfd2_latched = False
                    self.store.setValues(
                        CO, CO_RESET_HFD, [0]
                    )
                    logging.info(
                        "[%s] Reset HFD diterima.",
                        self.name,
                    )

                now = time.monotonic()

                if (
                    cmd1 != self.last_cmd_lbs1
                    and self.transit_lbs1 is None
                ):
                    self.last_cmd_lbs1 = cmd1
                    self.transit_lbs1 = cmd1
                    self.transit_end_lbs1 = (
                        now + TRANSIT_S
                    )
                    self._publish_positions(
                        True, False
                    )

                if (
                    cmd2 != self.last_cmd_lbs2
                    and self.transit_lbs2 is None
                ):
                    self.last_cmd_lbs2 = cmd2
                    self.transit_lbs2 = cmd2
                    self.transit_end_lbs2 = (
                        now + TRANSIT_S
                    )
                    self._publish_positions(
                        False, True
                    )

                if (
                    self.transit_lbs1 is not None
                    and now >= self.transit_end_lbs1
                ):
                    target = int(
                        self.transit_lbs1
                    )
                    self.transit_lbs1 = None
                    self.lbs1_closed = bool(target)
                    self._publish_positions(
                        False, False
                    )

                if (
                    self.transit_lbs2 is not None
                    and now >= self.transit_end_lbs2
                ):
                    target = int(
                        self.transit_lbs2
                    )
                    self.transit_lbs2 = None
                    self.lbs2_closed = bool(target)
                    self._publish_positions(
                        False, False
                    )

                self.store.setValues(
                    DI,
                    DI_HFD1,
                    [int(self.hfd1_latched)],
                )
                self.store.setValues(
                    DI,
                    DI_HFD2,
                    [int(self.hfd2_latched)],
                )

                await asyncio.sleep(CONTROL_STEP_S)

        except asyncio.CancelledError:
            raise


async def run_rtu(gd_number):
    if not 1 <= int(gd_number) <= 5:
        raise ValueError("Nomor GD harus 1..5")

    sim = GDSimulator(
        int(gd_number)
    )

    logging.info("======================================")
    logging.info(
        "RTU [%s] berjalan di port %d (Slave ID: %d)",
        sim.name,
        sim.port,
        SLAVE_ID,
    )
    logging.info(
        "GD HR0=HFD1, HR1=HFD2; "
        "fault aktif -> CSV seluruh RTU PAUSE",
    )
    logging.info(
        "DP: CLOSED=01, OPEN=10, TRANSIT=00"
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
        print("Usage: py rtu_gd.py 1..5")
        sys.exit(1)

    try:
        asyncio.run(
            run_rtu(int(sys.argv[1]))
        )
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        logging.error(
            "RTU GD gagal start: %s",
            exc,
        )
        sys.exit(1)
