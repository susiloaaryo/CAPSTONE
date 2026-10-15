#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bfs_flisr.py  --  Kerangka Backward-Forward Sweep (BFS) untuk jaringan FLISR 20 kV
=================================================================================
Capstone C-501 / D-01.  Topologi: GI SATU - GD01..GD05 - GI DUA (6 segmen kabel,
12 saklar, NOP normal = GD03.LBS2).

YANG DILAKUKAN
  1. Menyelesaikan aliran daya radial (per-fasa ekuivalen) dengan BFS.
  2. Mendukung banyak sumber (slack): tiap sumber menghidupi "pulau" radialnya
     sendiri. Jika dua sumber/loop tertutup bertemu -> LoopError (lihat bagian
     'KETERBATASAN').
  3. Model trafo distribusi (Zk dari uk & Pk, rugi besi P0 & Q0, tap).
  4. Model beban ZIP (default: arus-konstan, sama seperti draft C-501 4.4.2.3).
  5. Mensimulasikan hasil restorasi untuk 8 case FLISR (aturan D/L/I/R) lalu
     memeriksa: tegangan simpul (R4b), arus GI penyokong (R4), KHA kabel,
     pembebanan trafo.
  6. Sweep faktor skala beban untuk mencari titik di mana R4 mulai menolak.

DATA
  Semua masukan dibaca dari dummy_data.py. Nilai [KATALOG] bersumber dari dokumen proyek;
  nilai [ASUMSI] adalah data dummy (bukan data mitra) dan harus diberi label asumsi di laporan.

KETERBATASAN (jujur)
  - Per-fasa ekuivalen, seimbang. Tidak ada ketidakseimbangan fasa.
  - Kapasitansi kabel diabaikan (kecil pada 20 kV, jarak pendek).
  - Loop tertutup (dua GI paralel lewat NOP tertutup tanpa isolasi) tidak
    diselesaikan; program memunculkan LoopError. Perluasan: metode kompensasi
    (breakpoint) dengan  dI = (Va - Vb)/(Zth_a + Zth_b).
  - Impedansi sumber (Zth GI) belum dimodelkan; GI diperlakukan sebagai
    tegangan tetap (slack ideal). Isi Zth_GI jika Sk'' sudah ada.
  - Trafo: Zk dirujuk ke sisi 20 kV pada tap nominal; tap hanya menggeser rasio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# =============================================================================
# 1. KONFIGURASI  -- nilai diambil dari dummy_data.py (ganti berkas itu dengan data mitra)
# =============================================================================
import dummy_data as D

F_HZ = D.F_HZ
V_LL_KV = D.V_LL_KV
V_SOURCE_PU = dict(D.V_SOURCE_PU)
SOURCE_MODE = D.SOURCE_MODE           # "bus" | "emf"
ZTH_GI_OHM = dict(D.ZTH_GI_OHM)
C_VOLT = D.C_VOLT
V_MIN_KV = D.V_MIN_KV
V_MIN_ALT_KV = D.V_MIN_ALT_KV
V_MAX_KV = D.V_MAX_KV
I_MAX_GI_A = D.I_MAX_GI_A
CABLE = dict(D.CABLE)
SEG_LENGTH_KM = dict(D.SEG_LENGTH_KM)
TRAFO_DATA = D.TRAFO_DATA
TAP_STEP_PU = D.TAP_STEP_PU
GARDU = D.GARDU
LOAD_MODE = D.LOAD_MODE
LOAD_VALUE = dict(D.LOAD_VALUE)
POWER_FACTOR = D.POWER_FACTOR         # float, atau dict per gardu
PROFIL_24H = list(D.PROFIL_24H)

# Model ZIP: (z, i, p) harus berjumlah 1.  Draft memakai arus-konstan.
ZIP = {"constant_current": (0.0, 1.0, 0.0),
       "constant_power": (0.0, 0.0, 1.0),
       "constant_impedance": (1.0, 0.0, 0.0),
       "mixed_50p_30i_20z": (0.2, 0.3, 0.5)}
LOAD_MODEL = "constant_current"

USE_TRAFO_MODEL = True              # True: beban di sisi 0,4 kV lewat trafo; False: beban di simpul 20 kV
INCLUDE_NO_LOAD_LOSS = True         # rugi besi (P0, Q0) sebagai beban shunt di simpul 20 kV

# --- Numerik -----------------------------------------------------------------
TOL = 1e-8                          # toleransi |dV|/V_base
MAX_ITER = 100


# =============================================================================
# 2. STRUKTUR DATA
# =============================================================================
class LoopError(RuntimeError):
    """Jaringan hidup membentuk loop / dua sumber paralel (bukan radial)."""


@dataclass
class Branch:
    bid: str
    a: str                          # simpul sisi sumber (nominal)
    b: str
    z: complex                      # impedansi per fasa (ohm, dirujuk ke sisi 20 kV)
    kind: str                       # "line" | "trafo"
    switches: Tuple[str, ...] = ()  # saklar yang harus tertutup agar cabang hidup
    seg: Optional[int] = None
    kha_a: Optional[float] = None
    sn_kva: Optional[float] = None
    tap_factor: float = 1.0


@dataclass
class Network:
    nodes: List[str]
    sources: List[str]
    branches: Dict[str, Branch]
    node_s_va: Dict[str, complex]   # beban 3 fasa nominal (VA) per simpul
    node_shunt_va: Dict[str, complex]   # rugi besi trafo (VA) di simpul 20 kV
    node_tap: Dict[str, float]      # faktor tap untuk simpul LV
    switch_names: List[str]

    def normal_switches(self) -> Dict[str, bool]:
        sw = {s: True for s in self.switch_names}
        sw["GD03.LBS2"] = False     # NOP
        return sw


@dataclass
class Result:
    v_ph: Dict[str, complex]
    v_ll_kv: Dict[str, float]
    v_pu: Dict[str, float]
    branch_i_a: Dict[str, float]
    branch_loading: Dict[str, float]    # arus/KHA atau S/Sn
    source_i_a: Dict[str, float]
    source_pq_kva: Dict[str, Tuple[float, float]]
    loss_kw: float
    dead_nodes: List[str]
    iterations: int
    violations: List[str]
    lv_volt_v: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


# =============================================================================
# 3. PEMBANGUNAN JARINGAN
# =============================================================================
def cable_z_per_km() -> complex:
    x = 2 * math.pi * F_HZ * CABLE["l_mH_km"] * 1e-3
    return complex(CABLE["r_ohm_km"], x)


def trafo_params(kind: str) -> Tuple[complex, complex, float]:
    """Return (Zk di sisi 20 kV [ohm], S_shunt no-load [VA], Sn [kVA])."""
    d = TRAFO_DATA[kind]
    sn_va = d["sn_kva"] * 1e3
    rk = d["pk_w"] / sn_va                      # pu
    zk = d["uk"] / 100.0
    xk = math.sqrt(max(zk ** 2 - rk ** 2, 0.0))
    zbase = (V_LL_KV * 1e3) ** 2 / sn_va
    p0 = d["p0_w"]
    s0 = d["i0"] / 100.0 * sn_va
    q0 = math.sqrt(max(s0 ** 2 - p0 ** 2, 0.0))
    return complex(rk, xk) * zbase, complex(p0, q0), d["sn_kva"]


def trafo_equiv(kinds):
    """Paralel beberapa trafo (str atau list). Return (Zk_eq ohm, S0 total VA, Sn total kVA)."""
    if isinstance(kinds, str):
        kinds = [kinds]
    y, s0, sn = 0j, 0j, 0.0
    for k in kinds:
        zt, s, snk = trafo_params(k)
        y += 1 / zt
        s0 += s
        sn += snk
    return 1 / y, s0, sn


def load_va(gardu: str) -> complex:
    v = LOAD_VALUE[gardu]
    if LOAD_MODE == "A_20kV":
        s = math.sqrt(3) * V_LL_KV * 1e3 * v
    elif LOAD_MODE == "kVA":
        s = v * 1e3
    else:
        raise ValueError("LOAD_MODE harus 'A_20kV' atau 'kVA'")
    pf = POWER_FACTOR[gardu] if isinstance(POWER_FACTOR, dict) else POWER_FACTOR
    phi = math.acos(pf)
    return complex(s * math.cos(phi), s * math.sin(phi))   # lagging


def build_network() -> Network:
    gds = ["GD01", "GD02", "GD03", "GD04", "GD05"]
    nodes = ["GI1"] + gds + ["GI2"]
    sw = ["GI1.CB", "GI2.CB"] + [f"{g}.LBS{k}" for g in gds for k in (1, 2)]
    zc = cable_z_per_km()
    # ujung-ujung saklar tiap segmen (A = sisi GI SATU)
    ends = {
        1: ("GI1", "GD01", ("GI1.CB", "GD01.LBS1")),
        2: ("GD01", "GD02", ("GD01.LBS2", "GD02.LBS1")),
        3: ("GD02", "GD03", ("GD02.LBS2", "GD03.LBS1")),
        4: ("GD03", "GD04", ("GD03.LBS2", "GD04.LBS1")),
        5: ("GD04", "GD05", ("GD04.LBS2", "GD05.LBS1")),
        6: ("GD05", "GI2", ("GD05.LBS2", "GI2.CB")),
    }
    br: Dict[str, Branch] = {}
    for k, (a, b, s) in ends.items():
        br[f"SEG{k}"] = Branch(f"SEG{k}", a, b, zc * SEG_LENGTH_KM[k], "line", s, seg=k,
                               kha_a=CABLE["kha_A"] * CABLE.get("derating", 1.0))
    node_s: Dict[str, complex] = {}
    node_shunt: Dict[str, complex] = {}
    node_tap: Dict[str, float] = {}
    for g in gds:
        tk = GARDU[g]["trafo"]
        zt, s0, sn = trafo_equiv(tk)
        tf = 1.0 + GARDU[g]["tap"] * TAP_STEP_PU
        if USE_TRAFO_MODEL:
            lv = f"LV_{g}"
            nodes.append(lv)
            br[f"T_{g}"] = Branch(f"T_{g}", g, lv, zt, "trafo", (), sn_kva=sn, tap_factor=tf)
            node_s[lv] = load_va(g)
            node_tap[lv] = tf
            if INCLUDE_NO_LOAD_LOSS:
                node_shunt[g] = s0
        else:
            node_s[g] = load_va(g)
            node_tap[g] = 1.0
    return Network(nodes, ["GI1", "GI2"], br, node_s, node_shunt, node_tap, sw)


# =============================================================================
# 4. SOLVER BFS
# =============================================================================
def _in_service(b: Branch, sw: Dict[str, bool], out_of_service: set) -> bool:
    if b.bid in out_of_service:
        return False
    return all(sw[s] for s in b.switches)


def _energized_tree(net: Network, sw: Dict[str, bool], live_sources: List[str],
                    out_of_service: set):
    """BFS dari tiap sumber hidup. Return order, parent[node]=(parent, branch)."""
    adj: Dict[str, List[Tuple[str, Branch]]] = {n: [] for n in net.nodes}
    for b in net.branches.values():
        if _in_service(b, sw, out_of_service):
            adj[b.a].append((b.b, b))
            adj[b.b].append((b.a, b))
    parent: Dict[str, Optional[Tuple[str, Branch]]] = {}
    order: List[str] = []
    for src in live_sources:
        if src in parent:
            raise LoopError(f"Sumber {src} sudah terhubung ke sumber lain (paralel).")
        parent[src] = None
        queue = [src]
        while queue:
            u = queue.pop(0)
            order.append(u)
            for v, b in adj[u]:
                if parent.get(u) and parent[u][1] is b:
                    continue                                  # cabang asal
                if v in parent:
                    raise LoopError(
                        f"Loop/paralel sumber terdeteksi pada cabang {b.bid} ({u}-{v}). "
                        "Gunakan metode kompensasi atau pastikan isolasi selesai.")
                parent[v] = (u, b)
                queue.append(v)
    return order, parent


def solve(net: Network, sw: Optional[Dict[str, bool]] = None,
          live_sources: Optional[List[str]] = None, scale: float = 1.0,
          out_of_service: Optional[set] = None, model: Optional[str] = None) -> Result:
    sw = dict(sw) if sw is not None else net.normal_switches()
    live = list(net.sources if live_sources is None else live_sources)
    oos = set(out_of_service or ())
    z_i_p = ZIP[model or LOAD_MODEL]
    v0 = V_LL_KV * 1e3 / math.sqrt(3)               # tegangan fasa nominal (V)

    # sumber: tegangan efektif = slack di belakang Zth
    order, parent = _energized_tree(net, sw, live, oos)
    energized = set(order)
    v = {n: complex(v0 * V_SOURCE_PU.get(n, 1.0), 0) if parent[n] is None else complex(v0, 0)
         for n in order}
    v_src = {n: v[n] for n in order if parent[n] is None}

    def inj(n: str, vn: complex) -> complex:
        """Arus injeksi (A, per fasa) di simpul n pada tegangan vn."""
        i_tot = 0j
        s_load = net.node_s_va.get(n)
        if s_load is not None:
            tf = net.node_tap.get(n, 1.0)
            vr = abs(vn) / (v0 * tf)                # |V| terhadap nominal aktual
            zz, ii, pp = z_i_p
            s = s_load * scale * (zz * vr ** 2 + ii * vr + pp)
            i_tot += (s / 3.0 / vn).conjugate()
        s_sh = net.node_shunt_va.get(n)
        if s_sh is not None:
            vr = abs(vn) / v0
            i_tot += (s_sh * vr ** 2 / 3.0 / vn).conjugate()
        return i_tot

    it = 0
    for it in range(1, MAX_ITER + 1):
        acc = {n: inj(n, v[n]) for n in order}
        j: Dict[str, complex] = {}
        for n in reversed(order):                   # backward sweep
            p = parent[n]
            if p is not None:
                j[p[1].bid] = acc[n]
                acc[p[0]] += acc[n]
        vnew = {}
        for n in order:                             # forward sweep
            p = parent[n]
            if p is None:
                zs = ZTH_GI_OHM.get(n, 0j) if SOURCE_MODE == "emf" else 0j
                vnew[n] = v_src[n] - zs * acc[n]
            else:
                vnew[n] = vnew[p[0]] - p[1].z * j[p[1].bid]
        err = max(abs(vnew[n] - v[n]) for n in order) / v0
        v = vnew
        if err < TOL:
            break
    else:
        raise RuntimeError(f"BFS tidak konvergen dalam {MAX_ITER} iterasi (err={err:.2e})")

    # ---- pasca-pengolahan -----------------------------------------------------
    v_ll_kv = {n: abs(v[n]) * math.sqrt(3) / 1e3 for n in order}
    v_pu = {n: abs(v[n]) / v0 for n in order}
    bi = {k: abs(x) for k, x in j.items()}
    loading: Dict[str, float] = {}
    for bid, cur in j.items():
        b = net.branches[bid]
        if b.kind == "line":
            loading[bid] = abs(cur) / b.kha_a
        else:
            s_kva = math.sqrt(3) * V_LL_KV * abs(cur)       # kVA di sisi 20 kV (nominal)
            loading[bid] = s_kva / b.sn_kva
    # rugi (W): tembaga/kabel = 3 |I|^2 R ; besi = P0 * (V/V0)^2
    loss = sum(3 * abs(j[b]) ** 2 * net.branches[b].z.real for b in j)
    for n, s in net.node_shunt_va.items():
        if n in energized:
            loss += s.real * (abs(v[n]) / v0) ** 2
    src_i, src_pq = {}, {}
    for n in order:
        if parent[n] is None:
            itot = sum((j[parent[m][1].bid] for m in order
                        if parent[m] is not None and parent[m][0] == n), 0j)
            src_i[n] = abs(itot)
            s = 3 * v[n] * itot.conjugate()
            src_pq[n] = (s.real / 1e3, s.imag / 1e3)
    dead = [n for n in net.nodes if n not in energized]

    lv_v = {}
    for n in order:
        if n.startswith("LV_"):
            tf = net.node_tap[n]
            lv_v[n] = abs(v[n]) * math.sqrt(3) * (0.4 / V_LL_KV) / tf

    viol: List[str] = []
    for n in order:
        if n.startswith("LV_") or parent[n] is None:
            continue
        if v_ll_kv[n] < V_MIN_KV:
            viol.append(f"V({n})={v_ll_kv[n]:.3f} kV < {V_MIN_KV} kV")
        if v_ll_kv[n] > V_MAX_KV:
            viol.append(f"V({n})={v_ll_kv[n]:.3f} kV > {V_MAX_KV} kV")
    notes: List[str] = []
    for n in order:
        if not (n.startswith("LV_") or parent[n] is None) and V_MIN_KV <= v_ll_kv[n] < V_MIN_ALT_KV:
            notes.append(f"V({n})={v_ll_kv[n]:.3f} kV < {V_MIN_ALT_KV} kV (jika batas 19 kV dipakai)")
    for bid, ld in loading.items():
        if ld > 1.0:
            nm = "KHA" if net.branches[bid].kind == "line" else "Sn trafo"
            viol.append(f"{bid}: {ld * 100:.0f}% dari {nm}")
    for n, i in src_i.items():
        if i > I_MAX_GI_A:
            viol.append(f"I({n})={i:.1f} A > I_maks R4 {I_MAX_GI_A:.0f} A")

    return Result(v, v_ll_kv, v_pu, bi, loading, src_i, src_pq, loss / 1e3, dead, it,
                  viol, lv_v, notes)


# =============================================================================
# 5. SKENARIO FLISR (8 case) -- mengikuti Aturan_Algoritma_FLISR (D, L, I, R)
# =============================================================================
_NET0 = build_network()
SEG_SWITCHES = {i: _NET0.branches[f"SEG{i}"].switches for i in range(1, 7)}  # urut: (sisi GI SATU, sisi GI DUA)
CASE_TEXT = {1: "kabel 1 GI1-GD01", 2: "kabel 2 GD01-GD02", 3: "kabel 3 GD02-GD03",
             4: "kabel 4 GD03-GD04", 5: "kabel 5 GD04-GD05", 6: "kabel 6 GD05-GI2",
             7: "sumber GI SATU hilang", 8: "sumber GI DUA hilang"}


def flisr_case(net: Network, case: int, scale: float = 1.0, model: Optional[str] = None):
    """Mengembalikan (Result pasca-restorasi, log). Case 1-6 = gangguan kabel; 7/8 = sumber hilang."""
    sw = net.normal_switches()
    log: List[str] = []
    live = list(net.sources)
    oos: set = set()
    if 1 <= case <= 6:
        trig = "GI1" if case <= 3 else "GI2"
        cb = f"{trig}.CB"
        sw[cb] = False
        oos.add(f"SEG{case}")                       # kabel rusak (arus gangguan tidak dimodelkan)
        log.append(f"D: CB {trig} trip (proteksi). Segmen rusak = SEG{case}.")
        pair = SEG_SWITCHES[case] if trig == "GI2" else SEG_SWITCHES[case][::-1]
        for s in pair:                              # I1-I3: buka pengapit, yang JAUH dari sumber pemicu dulu
            if sw[s]:
                sw[s] = False
                log.append(f"I: buka {s}")
        if cb not in SEG_SWITCHES[case]:            # R1: CB boleh ditutup lagi
            sw[cb] = True
            log.append(f"R1: tutup kembali {cb}")
        else:
            log.append(f"R1: {cb} adalah pengapit -> TIDAK ditutup")
    elif case in (7, 8):
        lost = "GI1" if case == 7 else "GI2"
        live.remove(lost)
        log.append(f"L5: sumber {lost} hilang tegangan (UV), CB tetap tertutup; tanpa isolasi.")
    else:
        raise ValueError("case harus 1..8")

    r0 = solve(net, sw, live, scale, oos, model)
    if r0.dead_nodes and any(not n.startswith("LV_") and n not in net.sources for n in r0.dead_nodes):
        dead_gd = [n for n in r0.dead_nodes if n.startswith("GD")]
    else:
        dead_gd = []
    if not dead_gd:
        log.append("R3: tidak ada gardu padam -> NOP tidak ditutup.")
        return r0, log
    log.append(f"R2: gardu padam setelah CB ditutup: {dead_gd}")
    if sw["GD03.LBS2"]:
        log.append("R5: NOP sudah tertutup -> tidak ada cadangan. incomplete.")
        return r0, log
    sw["GD03.LBS2"] = True                          # R7: setelah isolasi terkonfirmasi
    log.append("R7/R4: tutup NOP GD03.LBS2 (cek kelayakan pada hasil di bawah).")
    r1 = solve(net, sw, live, scale, oos, model)
    return r1, log


# =============================================================================
# 6. SWEEP FAKTOR SKALA BEBAN  -> titik jatuh R4/R4b
# =============================================================================
def r4_sweep(net: Network, scales=None, model: Optional[str] = None):
    """Per case: (skala pertama R4/V melanggar, rows, skala pertama pelanggaran APA PUN, alasannya)."""
    scales = scales or [round(1.0 + 0.05 * k, 2) for k in range(0, 41)]
    table = {}
    for c in range(1, 9):
        first, first_any, why = None, None, ""
        rows = []
        for s in scales:
            r, _ = flisr_case(net, c, s, model)
            gi_i = max(r.source_i_a.values()) if r.source_i_a else 0.0
            vmin = min((r.v_ll_kv[n] for n in r.v_ll_kv if n.startswith("GD")), default=float("nan"))
            hard = [x for x in r.violations if x.startswith("I(") or x.startswith("V(")]
            rows.append((s, gi_i, vmin, hard))
            if first is None and hard:
                first = s
            if first_any is None and r.violations:
                first_any, why = s, r.violations[0]
        table[c] = (first, rows, first_any, why)
    return table


# =============================================================================
# 7. CETAK
# =============================================================================
def warn_placeholders():
    print("=" * 78)
    print(f"DATASET: {D.PROFIL}  -- DATA ASUMSI (DUMMY), bukan data mitra")
    print("  [KATALOG] kabel N2XSEY 3x150 Cu 12/20 kV (Voksel), trafo 400/630 kVA (Asata)")
    print("  [ASUMSI]  panjang segmen, beban & PF, penugasan trafo & tap, Sk'' GI, setpoint GI,")
    print("            derating KHA 0,80, profil harian. Label 'asumsi' wajib di laporan.")
    print("  Keputusan terbuka: batas tegangan 18 kV (draft) vs 19 kV (Aturan Algoritma).")
    print("=" * 78)


def print_dataset(net: Network):
    print("\n--- RINGKASAN DATASET ---")
    zc = cable_z_per_km()
    print(f"Kabel: r={CABLE['r_ohm_km']} ohm/km, x={zc.imag:.4f} ohm/km, KHA {CABLE['kha_A']:.0f} A "
          f"x derating {CABLE.get('derating', 1):.2f} = {CABLE['kha_A'] * CABLE.get('derating', 1):.0f} A")
    print("Segmen (km): " + ", ".join(f"{k}={v}" for k, v in SEG_LENGTH_KM.items())
          + f"  | total {sum(SEG_LENGTH_KM.values()):.1f} km")
    for src in ("GI1", "GI2"):
        z = ZTH_GI_OHM[src]
        print(f"{src}: Sk''={D.SK_MVA[src]:.0f} MVA, Zth={z.real:.3f}+j{z.imag:.3f} ohm (X/R={D.XR_GI:.0f}), "
              f"V setpoint={V_SOURCE_PU[src]:.3f} pu, mode={SOURCE_MODE}")
    print(f"{'Gardu':6} {'Trafo (kVA)':28} {'Sn tot':>7} {'S beban':>8} {'I 20kV':>7} {'PF':>5} {'pembebanan':>10}")
    for g in ("GD01", "GD02", "GD03", "GD04", "GD05"):
        kinds = GARDU[g]["trafo"]
        kinds = [kinds] if isinstance(kinds, str) else kinds
        sn = sum(TRAFO_DATA[k]["sn_kva"] for k in kinds)
        s = abs(load_va(g)) / 1e3
        pf = POWER_FACTOR[g] if isinstance(POWER_FACTOR, dict) else POWER_FACTOR
        print(f"{g:6} {'+'.join(kinds):28} {sn:7.0f} {s:8.0f} {s / (math.sqrt(3) * V_LL_KV):7.1f} {pf:5.2f} {s / sn * 100:9.0f}%")


# =============================================================================
# 6b. HUBUNG SINGKAT 3-FASA (pendekatan IEC 60909, tanpa kontribusi motor)  &  PROFIL 24 JAM
# =============================================================================
def fault_levels(net: Network, sw=None, live=None, c: Optional[float] = None):
    """Arus hubung singkat 3 fasa (kA) di tiap simpul 20 kV: Ik'' = c*Un/(sqrt3*|Zth + Z_jalur|).
    Zth sudah memuat c (Zth = c Un^2/Sk''), sehingga di busbar GI hasilnya = Sk''/(sqrt3 Un)."""
    c = C_VOLT if c is None else c
    sw = net.normal_switches() if sw is None else sw
    live = list(net.sources if live is None else live)
    order, parent = _energized_tree(net, sw, live, set())
    z = {}
    for n in order:
        if parent[n] is None:
            z[n] = ZTH_GI_OHM[n]
        else:
            z[n] = z[parent[n][0]] + parent[n][1].z
    out = {}
    for n in order:
        if n.startswith("LV_"):
            continue
        out[n] = c * V_LL_KV * 1e3 / math.sqrt(3) / abs(z[n]) / 1e3
    return out


def run_24h(net: Network, model: Optional[str] = None):
    rows = []
    for h, f in enumerate(PROFIL_24H):
        r = solve(net, scale=f, model=model)
        vmin = min(r.v_ll_kv[n] for n in r.v_ll_kv if n.startswith("GD"))
        p_src = sum(p for p, q in r.source_pq_kva.values())
        rows.append((h, f, r.source_i_a.get("GI1", 0.0), r.source_i_a.get("GI2", 0.0), vmin, r.loss_kw, p_src))
    return rows


def print_result(title: str, r: Result, log: Optional[List[str]] = None):
    print(f"\n--- {title} ---")
    if log:
        for l in log:
            print("   ", l)
    print(f"  iterasi BFS: {r.iterations}   rugi total: {r.loss_kw:.2f} kW")
    print("  Simpul 20 kV:   " + "  ".join(f"{n}={r.v_ll_kv[n]:.3f}kV"
                                           for n in r.v_ll_kv if not n.startswith("LV_")))
    if r.lv_volt_v:
        print("  Sisi 0,4 kV:    " + "  ".join(f"{n[3:]}={v:.0f}V" for n, v in r.lv_volt_v.items()))
    print("  Arus segmen:    " + "  ".join(f"{b}={r.branch_i_a[b]:.1f}A({r.branch_loading[b] * 100:.0f}%)"
                                           for b in r.branch_i_a if b.startswith("SEG")))
    print("  Trafo (S/Sn):   " + "  ".join(f"{b[2:]}={r.branch_loading[b] * 100:.0f}%"
                                           for b in r.branch_i_a if b.startswith("T_")))
    print("  Arus sumber:    " + "  ".join(f"{n}={i:.1f}A" for n, i in r.source_i_a.items()))
    if r.dead_nodes:
        print("  Padam:          " + ", ".join(n for n in r.dead_nodes if not n.startswith("LV_")))
    print("  Pelanggaran:    " + ("; ".join(r.violations) if r.violations else "tidak ada"))
    if r.notes:
        print("  Catatan:        " + "; ".join(r.notes))


def main():
    warn_placeholders()
    net = build_network()
    print_dataset(net)
    print("\n--- ARUS HUBUNG SINGKAT 3 FASA, konfigurasi normal (kA) ---")
    fl = fault_levels(net)
    print("  " + "  ".join(f"{n}={v:.2f}" for n, v in fl.items()))
    fl7 = fault_levels(net, sw={**net.normal_switches(), "GD03.LBS2": True}, live=["GI2"])
    print("  Disuplai hanya GI DUA lewat NOP tertutup (kasus terkecil di GD01): "
          + "  ".join(f"{n}={v:.2f}" for n, v in fl7.items() if n.startswith("GD")))
    print("  Catatan: C-501 menyuntikkan 250 A dan Ith=200 A; nilai riil berorde kiloampere.")
    print_result("KONDISI NORMAL (NOP terbuka)", solve(net))
    for c in range(1, 9):
        r, log = flisr_case(net, c)
        print_result(f"CASE {c}: {CASE_TEXT[c]}", r, log)
    print("\n=== SWEEP FAKTOR SKALA BEBAN (pasca-restorasi) ===")
    print("  case  R4/tegangan pertama melanggar   pelanggaran APA PUN pertama (termasuk trafo & KHA)")
    for c, (first, rows, fany, why) in r4_sweep(net).items():
        a = f"x{first:.2f}" if first else ">x3,00"
        b = f"x{fany:.2f}: {why}" if fany else ">x3,00"
        print(f"  {c:4d}  {a:>10}                         {b}")
    print("\n=== PROFIL 24 JAM, konfigurasi normal ===")
    rows = run_24h(net)
    print("  jam  faktor  I_GI1(A)  I_GI2(A)  Vmin_GD(kV)  rugi(kW)")
    for h, f, i1, i2, vm, ls, _ in rows:
        print(f"  {h:3d}  {f:6.2f}  {i1:8.1f}  {i2:8.1f}  {vm:11.3f}  {ls:8.1f}")
    loss_kwh = sum(r[5] for r in rows)
    e_kwh = sum(r[6] for r in rows)
    print(f"  Energi disuplai {e_kwh:,.0f} kWh/hari; rugi {loss_kwh:,.0f} kWh/hari ({loss_kwh / e_kwh * 100:.2f} %)")


if __name__ == "__main__":
    main()
