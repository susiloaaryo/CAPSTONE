"""Uji otomatis 80 percobaan (K1..K8 x 10) terhadap Controller FLISR.

Skrip ini meniru urutan yang dilakukan operator lewat HMI:
  1. RESET SISTEM  (SHG disable, reset lock-out, repair testbench, normalisasi topologi)
  2. SHG ENABLE, tunggu fase SIAGA
  3. Kirim fault case Kx ke System Behavior (handshake TRIGGER/APPLIED)
  4. Pantau IR fase Controller sampai SELESAI / SELESAI SEBAGIAN / LOCK-OUT
  5. Verifikasi: fase akhir, sasaran, gardu padam, dan posisi switch isolasi.

Semua register/alamat diambil dari topologi.py (sama dengan web_hmi.py).
"""

import sys
import time
from datetime import datetime

from pymodbus.client import ModbusTcpClient

import topologi as T

ULANGAN = int(sys.argv[1]) if len(sys.argv) > 1 else 10
LOGFILE = sys.argv[2] if len(sys.argv) > 2 else "hasil_uji_80.log"

HOST = T.HOST_SIMULATOR
UNIT = T.SLAVE_RTU
HR_CASE, HR_MODE, HR_REPAIR, HR_TRIGGER, HR_APPLIED = 0, 1, 2, 3, 4
NORMAL = [1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1]
NOP_IDX = 6
TERMINAL = (T.SELESAI, T.SELESAI_SEBAGIAN, T.LOCK_OUT)

ctrl = ModbusTcpClient(HOST, port=T.PORT_SHG, timeout=2)
tb = ModbusTcpClient(HOST, port=T.PORT_TESTBENCH, timeout=2)
out = open(LOGFILE, "w", encoding="utf-8")


def log(msg=""):
    print(msg, flush=True)
    out.write(msg + "\n")
    out.flush()


def ir():
    r = ctrl.read_input_registers(T.IR_FASE, 5, slave=UNIT)
    return None if r.isError() else r.registers


def posisi():
    r = ctrl.read_discrete_inputs(0, T.DI_SWITCH_BASE + 12, slave=UNIT)
    if r.isError():
        return None, False
    bits = [int(b) for b in r.bits[T.DI_SWITCH_BASE:T.DI_SWITCH_BASE + 12]]
    return bits, bool(r.bits[T.DI_KONFIG_NORMAL])


def switch_isolasi(case):
    """Indeks switch (urutan topologi.semua_switch) yang wajib OPEN."""
    if case in (7, 8):
        # Gangguan sumber: controller.py tidak membuka CB; cukup NOP ditutup.
        return []
    seg = case - 1
    kiri, kanan = T.bay_pengapit(seg)
    return [T.switch_index(*kiri), T.switch_index(*kanan)]


def reset_sistem():
    ctrl.write_coil(T.CO_SHG_ENABLE, False, slave=UNIT)
    ctrl.write_coil(T.CO_RESET_LOCK_OUT, True, slave=UNIT)
    tb.write_register(HR_REPAIR, 1, slave=UNIT)
    time.sleep(0.30)
    ctrl.write_register(T.HR_TEST_REPAIR, 1, slave=UNIT)
    batas = time.time() + 10
    while time.time() < batas:
        pos, normal = posisi()
        if pos == NORMAL and normal:
            return True
        time.sleep(0.2)
    return False


def enable_dan_siaga():
    ctrl.write_coil(T.CO_SHG_ENABLE, True, slave=UNIT)
    batas = time.time() + 15
    while time.time() < batas:
        r = ir()
        if r and r[0] == T.SIAGA:
            return True
        time.sleep(0.2)
    return False


def kirim_case(case):
    tb.write_register(HR_MODE, 0, slave=UNIT)
    tb.write_register(HR_CASE, case, slave=UNIT)
    r = tb.read_holding_registers(HR_TRIGGER, 2, slave=UNIT)
    if r.isError():
        # Testbench versi lama tanpa handshake TRIGGER/APPLIED: case langsung
        # diterapkan saat HR_CASE berubah. Beri waktu watcher (siklus 0,05 s).
        time.sleep(0.3)
        return 1
    r = r.registers
    seq = 1 if r[0] >= 65535 else r[0] + 1
    tb.write_register(HR_TRIGGER, seq, slave=UNIT)
    batas = time.time() + 10
    while time.time() < batas:
        a = tb.read_holding_registers(HR_APPLIED, 2, slave=UNIT)
        if not a.isError() and a.registers[0] == seq:
            return a.registers[1]
        time.sleep(0.05)
    return -1


def satu_percobaan(case):
    if not reset_sistem():
        return dict(ok=False, alasan="reset gagal")
    if not enable_dan_siaga():
        return dict(ok=False, alasan="tidak SIAGA")
    t0 = time.perf_counter()
    status_tb = kirim_case(case)
    if status_tb != 1:
        return dict(ok=False, alasan=f"testbench status={status_tb}")
    fase_dilalui = []
    batas = time.time() + T.T_SHG_TIMEOUT + 5
    r = None
    while time.time() < batas:
        r = ir()
        if r:
            if not fase_dilalui or fase_dilalui[-1] != r[0]:
                fase_dilalui.append(r[0])
            if r[0] in TERMINAL:
                break
        time.sleep(0.05)
    t_wall = time.perf_counter() - t0
    # Telemetri posisi di DI Controller diperbarui tiap siklus poll (T_POLL).
    time.sleep(T.T_POLL + 0.6)
    pos, _ = posisi()
    fase, sasaran, detik_ms, padam = r[0], r[1], r[2], r[3]
    wajib_open = switch_isolasi(case)
    iso_ok = pos is not None and all(pos[i] == 0 for i in wajib_open)
    nop_ok = pos is not None and pos[NOP_IDX] == 1 if case != 4 else True
    ok = (fase == T.SELESAI and sasaran == case and padam == 0 and iso_ok and nop_ok)
    return dict(
        ok=ok, fase=fase, sasaran=sasaran, t_ctrl=detik_ms / 1000.0,
        t_wall=t_wall, padam=pos and padam, pos=pos, wajib_open=wajib_open,
        jalur="->".join(T.NAMA_FASE[f].split(",")[0] for f in fase_dilalui),
        alasan="" if ok else "verifikasi gagal",
    )


def nama_kasus(case):
    if case <= 6:
        return "Kabel %d (%s)" % (case, T.nama_segmen(case - 1))
    return "Sumber %s hilang" % ("GI SATU" if case == 7 else "GI DUA")


def main():
    for c in (ctrl, tb):
        if not c.connect():
            log("Gagal terhubung ke %s:%s" % (c.comm_params.host, c.comm_params.port))
            sys.exit(1)

    mulai = datetime.now()
    log("=" * 96)
    log(" UJI OTOMATIS FLISR  K1-K8 x %d  (total %d percobaan)" % (ULANGAN, 8 * ULANGAN))
    log(" Controller %s:%d | Testbench %s:%d | mode direct Modbus (controller.py)"
        % (HOST, T.PORT_SHG, HOST, T.PORT_TESTBENCH))
    log(" Mulai: %s" % mulai.strftime("%Y-%m-%d %H:%M:%S"))
    log("=" * 96)
    log("%-4s %-3s %-4s %-17s %-4s %8s %8s %-30s %s"
        % ("No", "K", "Ul", "Fase akhir", "Sas", "t_ctrl", "t_total", "Switch 12 (CB1..CB2)", "Hasil"))
    log("-" * 96)

    rekap = {}
    no = 0
    for case in range(1, 9):
        for ul in range(1, ULANGAN + 1):
            no += 1
            h = satu_percobaan(case)
            rekap.setdefault(case, []).append(h)
            if "fase" in h:
                pos = "".join(str(b) for b in h["pos"]) if h["pos"] else "-"
                log("%-4d K%-2d %-4d %-17s %-4d %7.2fs %7.2fs %-30s %s"
                    % (no, case, ul, T.NAMA_FASE[h["fase"]].upper()[:17], h["sasaran"],
                       h["t_ctrl"], h["t_wall"], pos, "LULUS" if h["ok"] else "GAGAL"))
            else:
                log("%-4d K%-2d %-4d %-17s %s" % (no, case, ul, "-", "GAGAL: " + h["alasan"]))

    log("-" * 96)
    log(" REKAP PER KASUS")
    log("-" * 96)
    log(" %-3s %-34s %7s %10s %10s %10s" % ("K", "Skenario", "Lulus", "t_ctrl rt", "t_ctrl min", "t_ctrl maks"))
    total_lulus = 0
    semua_t = []
    for case, hs in rekap.items():
        lulus = sum(h["ok"] for h in hs)
        total_lulus += lulus
        ts = [h["t_ctrl"] for h in hs if "t_ctrl" in h]
        semua_t += ts
        if ts:
            log(" K%-2d %-34s %4d/%-2d %9.2fs %9.2fs %9.2fs"
                % (case, nama_kasus(case), lulus, len(hs),
                   sum(ts) / len(ts), min(ts), max(ts)))
        else:
            log(" K%-2d %-34s %4d/%-2d %10s %10s %10s"
                % (case, nama_kasus(case), lulus, len(hs), "-", "-", "-"))
    log("-" * 96)
    selesai = datetime.now()
    log(" TOTAL LULUS : %d/%d (%.1f %%)" % (total_lulus, no, 100.0 * total_lulus / no))
    if semua_t:
        log(" t_ctrl rata-rata seluruh percobaan : %.2f s (min %.2f s, maks %.2f s)"
            % (sum(semua_t) / len(semua_t), min(semua_t), max(semua_t)))
    else:
        log(" t_ctrl rata-rata seluruh percobaan : - (tidak ada percobaan yang terukur)")
    log(" Selesai: %s  (durasi uji %s)" % (selesai.strftime("%Y-%m-%d %H:%M:%S"),
                                          str(selesai - mulai).split(".")[0]))
    log(" Kriteria LULUS: fase SELESAI, sasaran = K, gardu padam = 0, switch pengapit")
    log(" titik gangguan OPEN, NOP GD03-LBS2 CLOSE (kecuali K4: NOP ikut mengapit kabel 4).")
    log("=" * 96)


if __name__ == "__main__":
    main()
