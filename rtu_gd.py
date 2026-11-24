"""RTU Gardu Distribusi (GD) - final FLISR simulator.

Endpoints (Modbus TCP 502):
    GD01 -> 192.168.250.9
    GD02 -> 192.168.250.5
    GD03 -> 192.168.250.6
    GD04 -> 192.168.250.7
    GD05 -> 192.168.250.8

Contract:
    Slave ID = 1, zero_mode=True
    FC01 CO0..9 mirrors EBC CoreDb CS0..9:
      HFD1, LBS1 CLOSE, LBS1 OPEN, LBS1 LOCAL, LBS1 REMOTE,
      HFD2, LBS2 CLOSE, LBS2 OPEN, LBS2 LOCAL, LBS2 REMOTE
    CO10=LBS1 level command; CO11=LBS2 level command; CO12=reset both HFDs
    EBC FC05 command writes at CS1/2/6/7 are translated to action events;
    EBC Command entries have reset destinations CS0/CS5 but no source points.
    These destination writes are translated to per-bay reset events if a
    reset source is mapped in Easergy Builder.
    HR0=forced HFD1; HR1=forced HFD2; HR2=current LBS1;
    HR3=current LBS2; HR4=voltage; HR5=selector LBS1; HR6=selector LBS2
    Selector HR value: 0=LOCAL, 1=REMOTE. Defaults REMOTE.

Multi-master / multi-client behavior:
    One shared datastore is served by a single Modbus TCP server on this RTU IP.
    Multiple TCP clients may connect concurrently. Unit ID 1 is retained for
    direct mode/testbench; the additional EBC Mdbm Unit ID comes from topologi.py.
    In mode Y, the server translates EBC FC05 command writes into simulator
    actions without overwriting the FC01 status image.

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
# FC01 status image in CO0..CO9; command coils are kept separate.
CO_STATUS = 1
HR = 3
IR = 4

# FC01 image aligned one-to-one with EBC M2..M6 / S2..S6 CS:0..9.
CO_HFD1 = 0
CO_LBS1_CLOSE = 1
CO_LBS1_OPEN = 2
CO_LBS1_LOCAL = 3
CO_LBS1_REMOTE = 4
CO_HFD2 = 5
CO_LBS2_CLOSE = 6
CO_LBS2_OPEN = 7
CO_LBS2_LOCAL = 8
CO_LBS2_REMOTE = 9

# Command coils are intentionally outside the FC01 status image.
CO_LBS1 = 10
CO_LBS2 = 11
CO_RESET_HFD = 12

HR_SELECTOR_LBS1 = 5  # 0=LOCAL, 1=REMOTE
HR_SELECTOR_LBS2 = 6  # 0=LOCAL, 1=REMOTE

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
        self.port = T.port_node(self.gd_number)

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

        ebc_command_map = {
            0: ("reset_hfd", 0),
            1: ("switch", 0, True),
            2: ("switch", 0, False),
            5: ("reset_hfd", 1),
            6: ("switch", 1, True),
            7: ("switch", 1, False),
        }
        self.coil_block = EBCCommandCoilDataBlock(
            0,
            [0] * 10 + [
                self.last_cmd_lbs1,
                self.last_cmd_lbs2,
                0,
            ],
            ebc_command_map,
        )
        self.store = ModbusSlaveContext(
            co=self.coil_block,
            # HR0..HR4 fault/measurement injection; HR5=LBS1 selector,
            # HR6=LBS2 selector. Selectors default REMOTE for FLISR demos.
            hr=ModbusSequentialDataBlock(
                0, [0] * 5 + [1, 1]
            ),
            ir=ModbusSequentialDataBlock(
                0, [0] * 4
            ),
            zero_mode=True,
        )

        downstream_unit_id = T.mdbm_unit_id(self.gd_number)
        slave_contexts = {
            unit_id: self.store
            for unit_id in sorted({SLAVE_ID, downstream_unit_id})
        }
        self.context = ModbusServerContext(
            slaves=slave_contexts,
            single=False,
        )

        self._publish_positions(False, False)
        self._publish_selector_status()
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

    def _publish_selector_status(self):
        """Publish selector feedback; invalid HR values publish neither bit."""
        modes = self.store.getValues(HR, HR_SELECTOR_LBS1, count=2)
        mode1, mode2 = int(modes[0]), int(modes[1])
        self.coil_block.set_internal(CO_LBS1_LOCAL, [int(mode1 == 0)])
        self.coil_block.set_internal(CO_LBS1_REMOTE, [int(mode1 == 1)])
        self.coil_block.set_internal(CO_LBS2_LOCAL, [int(mode2 == 0)])
        self.coil_block.set_internal(CO_LBS2_REMOTE, [int(mode2 == 1)])

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

        # EBC CS ordering interleaves each bay's protection, position and selector.
        self.coil_block.set_internal(CO_LBS1_OPEN, [b1[0]])
        self.coil_block.set_internal(CO_LBS1_CLOSE, [b1[1]])
        self.coil_block.set_internal(CO_LBS2_OPEN, [b2[0]])
        self.coil_block.set_internal(CO_LBS2_CLOSE, [b2[1]])

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
                self.coil_block.set_internal(
                    CO_HFD1, [int(self.hfd1_latched)]
                )
                self.coil_block.set_internal(
                    CO_HFD2, [int(self.hfd2_latched)]
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
                    CO, 10, count=3
                )

                cmd1 = int(coils[0])
                cmd2 = int(coils[1])
                reset = int(coils[2])
                modes = self.store.getValues(HR, HR_SELECTOR_LBS1, count=2)
                mode1, mode2 = int(modes[0]), int(modes[1])
                self._publish_selector_status()

                # Writes arriving through HUe Mdbm use the CoreDb CS command
                # coordinates (1/2 and 6/7). Consume them as events while
                # preserving those same addresses as FC01 status feedback.
                now = time.monotonic()
                for event in self.coil_block.pop_events():
                    if event[0] == "reset_hfd":
                        bay = int(event[1])
                        if bay == 0:
                            self.hfd1_latched = False
                            logging.info("[%s] EBC reset HFD1 diterima (FC05 CS:0).", self.name)
                        else:
                            self.hfd2_latched = False
                            logging.info("[%s] EBC reset HFD2 diterima (FC05 CS:5).", self.name)
                    elif event[0] == "switch":
                        _, bay, target = event
                        target = int(bool(target))
                        mode = mode1 if bay == 0 else mode2
                        if mode != 1:
                            logging.warning(
                                "[%s] EBC %s command ditolak: selector bay %d bukan REMOTE",
                                self.name, "CLOSE" if target else "OPEN", bay + 1,
                            )
                            continue
                        if bay == 0 and self.transit_lbs1 is None:
                            self.last_cmd_lbs1 = target
                            self.coil_block.set_internal(10, [target])
                            if int(self.lbs1_closed) != target:
                                self.transit_lbs1 = target
                                self.transit_end_lbs1 = now + TRANSIT_S
                                self._publish_positions(True, False)
                            logging.info(
                                "[%s] EBC command LBS1 -> %s",
                                self.name, "CLOSE" if target else "OPEN",
                            )
                        elif bay == 1 and self.transit_lbs2 is None:
                            self.last_cmd_lbs2 = target
                            self.coil_block.set_internal(11, [target])
                            if int(self.lbs2_closed) != target:
                                self.transit_lbs2 = target
                                self.transit_end_lbs2 = now + TRANSIT_S
                                self._publish_positions(False, True)
                            logging.info(
                                "[%s] EBC command LBS2 -> %s",
                                self.name, "CLOSE" if target else "OPEN",
                            )
                        else:
                            logging.warning("[%s] EBC command ditolak: LBS%d sedang transit", self.name, bay + 1)

                if reset:
                    self.hfd1_latched = False
                    self.hfd2_latched = False
                    self.coil_block.set_internal(CO_RESET_HFD, [0])
                    logging.info(
                        "[%s] Reset HFD diterima.",
                        self.name,
                    )

                # In LOCAL or invalid selector state, remote coil writes are
                # ignored and consumed so they cannot execute later on REMOTE.
                if mode1 == 1:
                    if (
                        cmd1 != self.last_cmd_lbs1
                        and self.transit_lbs1 is None
                    ):
                        self.last_cmd_lbs1 = cmd1
                        self.transit_lbs1 = cmd1
                        self.transit_end_lbs1 = now + TRANSIT_S
                        self._publish_positions(True, False)
                else:
                    self.last_cmd_lbs1 = cmd1

                if mode2 == 1:
                    if (
                        cmd2 != self.last_cmd_lbs2
                        and self.transit_lbs2 is None
                    ):
                        self.last_cmd_lbs2 = cmd2
                        self.transit_lbs2 = cmd2
                        self.transit_end_lbs2 = now + TRANSIT_S
                        self._publish_positions(False, True)
                else:
                    self.last_cmd_lbs2 = cmd2

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

                self.coil_block.set_internal(
                    CO_HFD1, [int(self.hfd1_latched)]
                )
                self.coil_block.set_internal(
                    CO_HFD2, [int(self.hfd2_latched)]
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
        "RTU [%s] berjalan di %s:%d (Unit ID aktif: %s)",
        sim.name,
        T.ip_node(sim.gd_number),
        sim.port,
        sorted({SLAVE_ID, T.mdbm_unit_id(sim.gd_number)}),
    )
    logging.info(
        "GD HR0=HFD1, HR1=HFD2; "
        "fault aktif -> CSV seluruh RTU PAUSE",
    )
    logging.info(
        "DP: CLOSED=01, OPEN=10, TRANSIT=00"
    )
    logging.info(
        "Multi-client ready: direct/testbench Unit ID 1 + EBC Mdbm Unit ID "
        f"{T.mdbm_unit_id(sim.gd_number)}; FC01 status / FC05 EBC commands."
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
            address=(T.ip_node(sim.gd_number), sim.port),
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
