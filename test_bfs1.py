#!/usr/bin/env python3
"""Uji verifikasi independen untuk bfs_flisr.py (jalankan: python3 -I test_bfs.py)."""
import math
import sys

import bfs_flisr1 as m

ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(f"[{'LULUS' if cond else 'GAGAL'}] {name} {info}")


# ---- Uji 1: kasus analitik. Satu penyulang, beban impedansi-konstan di GD01,
#      tanpa trafo, tanpa rugi besi -> V = Vs * Zl / (Zl + Zline) (eksak).
m.USE_TRAFO_MODEL = False
m.INCLUDE_NO_LOAD_LOSS = False
m.LOAD_MODE = "kVA"
m.LOAD_VALUE = {"GD01": 1000.0, "GD02": 0.0, "GD03": 0.0, "GD04": 0.0, "GD05": 0.0}
m.POWER_FACTOR = 0.85
m.V_SOURCE_PU = {"GI1": 1.0, "GI2": 1.0}
m.SOURCE_MODE = "bus"
net = m.build_network()
r = m.solve(net, model="constant_impedance")
v0 = m.V_LL_KV * 1e3 / math.sqrt(3)
s = complex(1e6 * 0.85, 1e6 * math.sin(math.acos(0.85)))
zl = (v0 ** 2) / (s / 3).conjugate()            # beban Z-konstan per fasa
zline = m.cable_z_per_km() * m.SEG_LENGTH_KM[1]
v_analitik = v0 * zl / (zl + zline)
err = abs(abs(r.v_ph["GD01"]) - abs(v_analitik)) / v0
check("Analitik beban-Z (GD01)", err < 1e-9, f"galat relatif {err:.2e}")

# ---- Uji 2: residual KCL dengan matriks admitansi independen (numpy), jaringan penuh
try:
    import numpy as np
except ImportError:
    np = None
    print("[LEWAT] numpy tidak tersedia; uji KCL dilewati")

if np is not None:
    m.USE_TRAFO_MODEL = True
    m.INCLUDE_NO_LOAD_LOSS = True
    m.LOAD_MODE = m.D.LOAD_MODE
    m.LOAD_VALUE = dict(m.D.LOAD_VALUE)
    m.POWER_FACTOR = m.D.POWER_FACTOR
    net = m.build_network()
    for model in ("constant_current", "constant_power", "mixed_50p_30i_20z"):
        for closed_nop in (False, True):
            sw = net.normal_switches()
            live = list(net.sources)
            if closed_nop:
                sw["GD03.LBS2"] = True
                sw["GI2.CB"] = False              # satu sumber saja agar radial
            res = m.solve(net, sw, live, model=model)
            nodes = [n for n in res.v_ph]
            idx = {n: i for i, n in enumerate(nodes)}
            Y = np.zeros((len(nodes), len(nodes)), complex)
            for b in net.branches.values():
                if all(sw[x] for x in b.switches) and b.a in idx and b.b in idx:
                    y = 1 / b.z
                    i, j = idx[b.a], idx[b.b]
                    Y[i, i] += y; Y[j, j] += y; Y[i, j] -= y; Y[j, i] -= y
            V = np.array([res.v_ph[n] for n in nodes])
            I = Y @ V                               # arus yang MENGALIR KELUAR simpul ke cabang = -(arus beban)
            z, ii, pp = m.ZIP[model]
            worst = 0.0
            for n in nodes:
                if n in net.sources:
                    continue
                inj = 0j
                if n in net.node_s_va:
                    tf = net.node_tap.get(n, 1.0)
                    vr = abs(V[idx[n]]) / (v0 * tf)
                    sl = net.node_s_va[n] * (z * vr ** 2 + ii * vr + pp)
                    inj += (sl / 3 / V[idx[n]]).conjugate()
                if n in net.node_shunt_va:
                    vr = abs(V[idx[n]]) / v0
                    inj += (net.node_shunt_va[n] * vr ** 2 / 3 / V[idx[n]]).conjugate()
                worst = max(worst, abs(I[idx[n]] + inj))   # KCL: sum arus cabang keluar + arus beban = 0
            check(f"KCL independen [{model}, NOP {'tutup' if closed_nop else 'buka'}]",
                  worst < 1e-5, f"residu maks {worst:.2e} A")

# ---- Uji 3: kekekalan daya: P sumber = P beban + rugi
m.USE_TRAFO_MODEL = True
net = m.build_network()
res = m.solve(net, model="constant_power")
p_src = sum(p for p, q in res.source_pq_kva.values())
p_load = sum(s.real for s in net.node_s_va.values()) / 1e3
check("Neraca daya aktif (P_sumber = P_beban + rugi)", abs(p_src - (p_load + res.loss_kw)) < 1e-3,
      f"P_src={p_src:.3f} kW, P_load+loss={p_load + res.loss_kw:.3f} kW")

# ---- Uji 4: loop harus ditolak
sw = net.normal_switches(); sw["GD03.LBS2"] = True
try:
    m.solve(net, sw)
    check("LoopError saat NOP ditutup tanpa isolasi", False)
except m.LoopError:
    check("LoopError saat NOP ditutup tanpa isolasi", True)

# ---- Uji 5: konsistensi parameter katalog/datasheet
x = m.cable_z_per_km().imag
check("x kabel = 0,1100 ohm/km", abs(x - 0.10996) < 1e-4, f"x={x:.5f}")
zt, s0, sn = m.trafo_params("630")
check("Zk trafo 630 kVA = 4,25% pada 20 kV", abs(abs(zt) / (400e6 / 630e3) - 0.0425) < 1e-9)

# ---- Uji 6: trafo paralel, hubung singkat, mode sumber
z1, _, _ = m.trafo_params("630")
z2, _, sn2 = m.trafo_equiv(["630", "630"])
check("Dua trafo 630 paralel: Z/2 dan Sn=1260", abs(z2 - z1 / 2) < 1e-9 and sn2 == 1260.0)
net = m.build_network()
fl = m.fault_levels(net)
exp = m.D.SK_MVA["GI1"] / (math.sqrt(3) * m.V_LL_KV)
check("Ik'' busbar GI1 = Sk''/(sqrt3 Un)", abs(fl["GI1"] - exp) < 1e-9, f"{fl['GI1']:.4f} kA vs {exp:.4f} kA")
check("Ik'' turun menjauhi GI (GD01 > GD02 > GD03)", fl["GD01"] > fl["GD02"] > fl["GD03"])
m.SOURCE_MODE = "bus"
m.V_SOURCE_PU = {"GI1": 1.025, "GI2": 1.025}
res = m.solve(net)
check("Mode bus: tegangan busbar GI = setpoint", abs(res.v_pu["GI1"] - 1.025) < 1e-12)

print("\nHASIL AKHIR:", "SEMUA LULUS" if ok else "ADA YANG GAGAL")
sys.exit(0 if ok else 1)