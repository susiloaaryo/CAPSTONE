import csv
import html
import time
from pathlib import Path

import streamlit as st
from pymodbus.client import ModbusTcpClient


# ============================================================
# KONFIGURASI
# ============================================================

HOST = "127.0.0.1"
CONTROLLER_PORT = 503
SYSTEM_BEHAVIOR_PORT = 8027
SLAVE_ID = 1

# RTU ports sesuai kontrak
RTU_PORTS = {
    "GI SATU": 8020,
    "GD01": 8021,
    "GD02": 8022,
    "GD03": 8023,
    "GD04": 8024,
    "GD05": 8025,
    "GI DUA": 8026,
}

# Controller DI
DI_SHG_ACTIVE = 0
DI_SHG_IN_PROGRESS = 1
DI_SHG_INCOMPLETE = 2
DI_RTU_ONLINE = 4
DI_ALL_ONLINE = 11
DI_CONFIG_NORMAL = 12
DI_LOCKOUT = 13
# 14..25 = 12 switch positions in Controller DI
DI_SWITCH_BASE = 14

# Controller CO
CO_SHG_ENABLE = 0
CO_RESET_LOCKOUT = 1

# Controller IR
IR_PHASE = 0
IR_TARGET = 1
IR_DURATION = 2
IR_PADAM = 3
IR_EVENT = 4
IR_RTU_ONLINE = 5

# System Behavior 8027 HR
HR_CASE = 0
HR_MODE = 1
HR_REPAIR = 2

# Controller test/demo HR
# HR6 = repair + normalize topology
HR_CONTROLLER_REPAIR = 6

PHASE_NAME = {
    0: "MENUNGGU RTU",
    1: "SHG DISABLE",
    2: "BELUM SIAGA",
    3: "SIAGA",
    4: "LOKALISASI",
    5: "ISOLASI",
    6: "RESTORASI",
    7: "SELESAI",
    8: "SELESAI SEBAGIAN",
    9: "LOCK-OUT",
}

PHASE_DESC = {
    0: "Menunggu seluruh RTU menjawab",
    1: "SHG dinonaktifkan operator",
    2: "Kondisi awal belum terpenuhi",
    3: "Sistem siaga dan memantau",
    4: "Controller mencari lokasi gangguan",
    5: "Controller mengisolasi segmen rusak",
    6: "Controller memulihkan suplai",
    7: "Penanganan selesai",
    8: "Sebagian penanganan berhasil",
    9: "Menunggu reset operator",
}

SEGMENT_NAMES = [
    "GI SATU - GD01",
    "GD01 - GD02",
    "GD02 - GD03",
    "GD03 - GD04",
    "GD04 - GD05",
    "GD05 - GI DUA",
]

SOE_FILE = Path(__file__).with_name("soe.csv")


# ============================================================
# PAGE STYLE
# ============================================================

st.set_page_config(
    page_title="Web SCADA - Grid FLISR",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
html, body, [data-testid="stAppViewContainer"] {
    background: #eef1f5;
}

[data-testid="stHeader"] {
    background: #eef1f5;
}

.block-container {
    max-width: 1720px;
    padding-top: 1.0rem;
    padding-bottom: 2.5rem;
}

[data-testid="stSidebar"] {
    background: #e9edf2;
    border-right: 1px solid #d6dce5;
}

h1, h2, h3, h4 {
    color: #172033 !important;
}

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #d9dfe8;
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow: 0 1px 5px rgba(17, 24, 39, 0.05);
}

[data-testid="stMetricLabel"] {
    color: #68758a !important;
}

[data-testid="stMetricValue"] {
    color: #172033 !important;
    font-weight: 750;
}

.stButton > button {
    border-radius: 9px;
    min-height: 40px;
    font-weight: 650;
    border: 1px solid #cdd5e1;
    background: #ffffff;
}

.stButton > button:hover {
    border-color: #8391a5;
}

.scada-header {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:20px;
    background:#ffffff;
    border:1px solid #d9dfe8;
    border-radius:14px;
    padding:15px 18px;
    margin-bottom:12px;
    box-shadow:0 2px 8px rgba(15,23,42,.05);
}

.scada-title {
    font-size:24px;
    font-weight:800;
    color:#172033;
}

.scada-sub {
    color:#66748a;
    font-size:12px;
    margin-top:2px;
}

.live {
    color:#0d8a55;
    font-size:12px;
    font-weight:750;
    background:#e7f8ef;
    border:1px solid #bdebd3;
    padding:7px 11px;
    border-radius:999px;
}

.dot {
    display:inline-block;
    width:8px;
    height:8px;
    margin-right:6px;
    border-radius:50%;
    background:#16a66b;
    box-shadow:0 0 8px rgba(22,166,107,.4);
}

.section {
    color:#1c2738;
    font-size:17px;
    font-weight:800;
    margin:16px 0 8px;
}

.banner {
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    padding:9px 11px;
    background:#ffffff;
    border:1px solid #d9dfe8;
    border-radius:11px;
}

.chip {
    border-radius:999px;
    padding:5px 9px;
    font-size:11px;
    font-weight:700;
    background:#f3f5f8;
    border:1px solid #d8dee8;
    color:#49566b;
}

.chip.ok { background:#e8f8ef; border-color:#bfe9d1; color:#0c8a55; }
.chip.warn { background:#fff6df; border-color:#f0dfab; color:#9b6a00; }
.chip.bad { background:#ffecee; border-color:#efc1c9; color:#b42334; }

.summary-card {
    background:#ffffff;
    border:1px solid #d9dfe8;
    border-radius:12px;
    padding:14px 15px;
    min-height:112px;
    box-shadow:0 1px 5px rgba(17,24,39,.04);
}

.summary-kicker {
    color:#768399;
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.08em;
}

.summary-value {
    color:#172033;
    font-size:18px;
    font-weight:800;
    margin-top:5px;
}

.summary-note {
    color:#69778c;
    font-size:11px;
    margin-top:4px;
}

.side-note {
    background:#f7f9fb;
    border:1px dashed #cbd4df;
    border-radius:10px;
    padding:9px 10px;
    color:#66748a;
    font-size:11px;
    line-height:1.4;
}

.small-muted {
    color:#79869a;
    font-size:11px;
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# MODBUS HELPERS
# ============================================================

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def mb_read(port, point_type, address, count):
    client = ModbusTcpClient(HOST, port=port, timeout=0.8)
    if not client.connect():
        return None, f"Port {port} tidak dapat dihubungi."

    try:
        if point_type == "di":
            response = client.read_discrete_inputs(
                address, count, slave=SLAVE_ID
            )
            values = list(getattr(response, "bits", []) or [])
        elif point_type == "co":
            response = client.read_coils(
                address, count, slave=SLAVE_ID
            )
            values = list(getattr(response, "bits", []) or [])
        elif point_type == "ir":
            response = client.read_input_registers(
                address, count, slave=SLAVE_ID
            )
            values = list(getattr(response, "registers", []) or [])
        elif point_type == "hr":
            response = client.read_holding_registers(
                address, count, slave=SLAVE_ID
            )
            values = list(getattr(response, "registers", []) or [])
        else:
            return None, "Tipe register tidak dikenal."

        if response is None or response.isError():
            return None, f"Modbus error :{port} -> {response}"

        return values, None
    except Exception as exc:
        return None, str(exc)
    finally:
        client.close()


def mb_write(port, point_type, address, value):
    client = ModbusTcpClient(HOST, port=port, timeout=0.8)
    if not client.connect():
        return False, f"Port {port} tidak dapat dihubungi."

    try:
        if point_type == "coil":
            response = client.write_coil(
                address, bool(value), slave=SLAVE_ID
            )
        elif point_type == "hr":
            response = client.write_register(
                address, int(value), slave=SLAVE_ID
            )
        else:
            return False, "Jenis write tidak dikenal."

        if response is None or response.isError():
            return False, f"Modbus write gagal :{port} -> {response}"

        return True, None
    except Exception as exc:
        return False, str(exc)
    finally:
        client.close()


def read_controller():
    co, err = mb_read(CONTROLLER_PORT, "co", 0, 2)
    if err:
        return None, err

    di, err = mb_read(CONTROLLER_PORT, "di", 0, 16)
    if err:
        return None, err

    ir, err = mb_read(CONTROLLER_PORT, "ir", 0, 6)
    if err:
        return None, err

    return {
        "coils": co,
        "di": di,
        "ir": ir,
    }, None


def read_rtus():
    result = {}

    for name, port in RTU_PORTS.items():
        if name.startswith("GI"):
            di, de = mb_read(port, "di", 0, 5)
            ir, ie = mb_read(port, "ir", 0, 3)

            if de or ie:
                result[name] = {
                    "online": False,
                    "di": [],
                    "ir": [],
                    "error": de or ie,
                }
            else:
                result[name] = {
                    "online": True,
                    "di": di,
                    "ir": ir,
                    "error": None,
                }

        else:
            di, de = mb_read(port, "di", 0, 10)
            ir, ie = mb_read(port, "ir", 0, 3)

            if de or ie:
                result[name] = {
                    "online": False,
                    "di": [],
                    "ir": [],
                    "error": de or ie,
                }
            else:
                result[name] = {
                    "online": True,
                    "di": di,
                    "ir": ir,
                    "error": None,
                }

    return result


def read_behavior():
    hr, err = mb_read(SYSTEM_BEHAVIOR_PORT, "hr", 0, 3)
    if err:
        return None, err

    return {
        "case": safe_int(hr[HR_CASE]) if len(hr) > HR_CASE else 0,
        "mode": safe_int(hr[HR_MODE]) if len(hr) > HR_MODE else 0,
        "repair": safe_int(hr[HR_REPAIR]) if len(hr) > HR_REPAIR else 0,
    }, None


# ============================================================
# DP STATUS
# ============================================================

def dp_status(bits, open_index, close_index):
    if len(bits) <= max(open_index, close_index):
        return "INVALID", False, False

    op = int(bool(bits[open_index]))
    cl = int(bool(bits[close_index]))

    if op == 1 and cl == 0:
        return "OPEN", False, True
    if op == 0 and cl == 1:
        return "CLOSE", True, True
    if op == 0 and cl == 0:
        return "TRANSIT", False, True
    return "INVALID", False, False


def gd_status(info):
    di = info.get("di", [])
    lbs1_name, lbs1_closed, lbs1_valid = dp_status(di, 0, 1)
    lbs2_name, lbs2_closed, lbs2_valid = dp_status(di, 4, 5)

    hfd = bool(di[2]) or bool(di[6]) if len(di) >= 7 else False
    uv = bool(di[8]) if len(di) > 8 else False
    ov = bool(di[9]) if len(di) > 9 else False
    current = safe_int(info["ir"][0]) if len(info.get("ir", [])) > 0 else 0
    voltage = safe_int(info["ir"][2]) if len(info.get("ir", [])) > 2 else 0

    return {
        "lbs1": lbs1_name,
        "lbs1_closed": lbs1_closed,
        "lbs1_valid": lbs1_valid,
        "lbs2": lbs2_name,
        "lbs2_closed": lbs2_closed,
        "lbs2_valid": lbs2_valid,
        "hfd": hfd,
        "uv": uv,
        "ov": ov,
        "current": current,
        "voltage": voltage,
    }


def gi_status(info):
    di = info.get("di", [])
    cb_name, cb_closed, cb_valid = dp_status(di, 0, 1)
    trip = bool(di[2]) if len(di) > 2 else False
    uv = bool(di[3]) if len(di) > 3 else False
    ov = bool(di[4]) if len(di) > 4 else False
    current = safe_int(info["ir"][0]) if len(info.get("ir", [])) > 0 else 0
    voltage = safe_int(info["ir"][2]) if len(info.get("ir", [])) > 2 else 0

    return {
        "cb": cb_name,
        "cb_closed": cb_closed,
        "cb_valid": cb_valid,
        "trip": trip,
        "uv": uv,
        "ov": ov,
        "current": current,
        "voltage": voltage,
    }


# ============================================================
# SVG COMPONENTS — SAMA SEPERTI REFERENSI USER
# ============================================================

def draw_lbs(x, y, status, label):
    if status == "CLOSE":
        color = "#10b981"
        blade = f"M {x} {y+10} L {x} {y+30}"
    elif status == "OPEN":
        color = "#ef4444"
        blade = f"M {x} {y+10} L {x+12} {y+25}"
    elif status == "TRANSIT":
        color = "#f59e0b"
        blade = f"M {x} {y+10} L {x+7} {y+20}"
    else:
        color = "#64748b"
        blade = f"M {x} {y+10} L {x+5} {y+18}"

    tx = x - 30 if "1" in label else x + 10

    return f"""
    <line x1="{x}" y1="{y}" x2="{x}" y2="{y+10}"
          stroke="#94a3b8" stroke-width="2"/>
    <path d="{blade}" stroke="{color}" stroke-width="3"
          fill="none" stroke-linecap="round"/>
    <line x1="{x}" y1="{y+30}" x2="{x}" y2="{y+40}"
          stroke="#94a3b8" stroke-width="2"/>
    <text x="{tx}" y="{y+22}" font-size="10"
          fill="#cbd5e1" font-family="sans-serif">{html.escape(label)}</text>
    <text x="{tx}" y="{y+34}" font-size="8"
          fill="{color}" font-family="sans-serif">{status}</text>
    """


def draw_gi(x, name, cb_status, fault=False):
    color = "#10b981" if cb_status == "CLOSE" else "#ef4444" if cb_status == "OPEN" else "#f59e0b"
    alert = '<text x="{}" y="138" font-size="10" fill="#ef4444" text-anchor="middle" font-weight="bold" class="blinking">TRIP / UV</text>'.format(x) if fault else ""

    return f"""
    <line x1="{x-40}" y1="50" x2="{x+40}" y2="50"
          stroke="#b91c1c" stroke-width="4"/>
    <text x="{x}" y="40" font-size="12" fill="white"
          font-weight="bold" text-anchor="middle">{html.escape(name)}</text>
    <text x="{x+45}" y="53" font-size="10" fill="#94a3b8">20kV</text>

    <line x1="{x}" y1="50" x2="{x}" y2="80"
          stroke="#94a3b8" stroke-width="2"/>

    <rect x="{x-10}" y="80" width="20" height="20"
          fill="{color}" stroke="black" stroke-width="1"/>
    <text x="{x+15}" y="95" font-size="10" fill="#cbd5e1">CB</text>
    <text x="{x}" y="114" font-size="9" fill="{color}"
          text-anchor="middle">{cb_status}</text>

    <line x1="{x}" y1="100" x2="{x}" y2="150"
          stroke="#94a3b8" stroke-width="2"/>
    {alert}
    """


def draw_gd(x, name, lbs1_status, lbs2_status, arus, fault=False, is_nop=False, hfd=False, uv=False, ov=False):
    nop_text = (
        f'<text x="{x+27}" y="201" font-size="10" fill="#f59e0b" '
        f'font-weight="bold">NOP</text>'
        if is_nop else ""
    )

    if hfd:
        status_text = '<text x="{}" y="415" font-size="12" fill="#ef4444" text-anchor="middle" font-weight="bold" class="blinking">TRIP / HFD</text>'.format(x)
    elif uv:
        status_text = '<text x="{}" y="415" font-size="11" fill="#f59e0b" text-anchor="middle" font-weight="bold" class="blinking">⚠ UV</text>'.format(x)
    elif ov:
        status_text = '<text x="{}" y="415" font-size="11" fill="#f59e0b" text-anchor="middle" font-weight="bold" class="blinking">⚠ OV</text>'.format(x)
    else:
        status_text = '<text x="{}" y="415" font-size="11" fill="#10b981" text-anchor="middle">✅ AMAN</text>'.format(x)

    return f"""
    <line x1="{x-20}" y1="150" x2="{x-20}" y2="170"
          stroke="#94a3b8" stroke-width="2"/>
    <line x1="{x+20}" y1="150" x2="{x+20}" y2="170"
          stroke="#94a3b8" stroke-width="2"/>

    {draw_lbs(x-20, 170, lbs1_status, "LBS1")}
    {draw_lbs(x+20, 170, lbs2_status, "LBS2")}
    {nop_text}

    <line x1="{x-20}" y1="210" x2="{x-20}" y2="230"
          stroke="#94a3b8" stroke-width="2"/>
    <line x1="{x+20}" y1="210" x2="{x+20}" y2="230"
          stroke="#94a3b8" stroke-width="2"/>

    <line x1="{x-40}" y1="230" x2="{x+40}" y2="230"
          stroke="#b91c1c" stroke-width="4"/>
    <text x="{x-45}" y="234" font-size="12" fill="white"
          font-weight="bold" text-anchor="end">{html.escape(name)}</text>
    <text x="{x+45}" y="234" font-size="10" fill="#94a3b8">20kV</text>

    <line x1="{x}" y1="230" x2="{x}" y2="250"
          stroke="#94a3b8" stroke-width="2"/>
    <rect x="{x-8}" y="250" width="16" height="16"
          fill="#7f1d1d" stroke="black" stroke-width="1"/>
    <text x="{x+12}" y="262" font-size="9" fill="#cbd5e1">CBOG</text>

    <line x1="{x}" y1="266" x2="{x}" y2="295"
          stroke="#94a3b8" stroke-width="2"/>

    <circle cx="{x}" cy="305" r="10" fill="none"
            stroke="#10b981" stroke-width="2"/>
    <circle cx="{x}" cy="317" r="10" fill="none"
            stroke="#10b981" stroke-width="2"/>

    <line x1="{x}" y1="327" x2="{x}" y2="340"
          stroke="#94a3b8" stroke-width="2"/>
    <line x1="{x-6}" y1="340" x2="{x+6}" y2="340"
          stroke="#94a3b8" stroke-width="1"/>
    <line x1="{x-4}" y1="344" x2="{x+4}" y2="344"
          stroke="#94a3b8" stroke-width="1"/>
    <line x1="{x-2}" y1="348" x2="{x+2}" y2="348"
          stroke="#94a3b8" stroke-width="1"/>

    <rect x="{x-25}" y="365" width="50" height="20"
          fill="#020617" stroke="#334155" rx="3"/>
    <text x="{x}" y="380" font-size="13" fill="#00e5ff"
          text-anchor="middle" font-family="monospace"
          font-weight="bold">{arus}A</text>

    {status_text}
    """


def draw_fault_icon(x, y, is_active):
    if not is_active:
        return ""
    return (
        f'<polygon points="{x},{y-15} {x-8},{y+2} {x-2},{y+2} '
        f'{x-5},{y+15} {x+8},{y-2} {x+2},{y-2}" '
        f'fill="#facc15" stroke="#ca8a04" stroke-width="1" class="blinking" />'
    )


def build_sld(rtus, controller):
    ir = controller["ir"]
    di = controller["di"]

    phase = safe_int(ir[IR_PHASE])
    target = safe_int(ir[IR_TARGET])

    def online_bit(node):
        idx = DI_RTU_ONLINE + node
        return bool(di[idx]) if idx < len(di) else False

    positions = {}
    for i, name in enumerate(RTU_PORTS):
        positions[name] = online_bit(i)

    gi1 = gi_status(rtus["GI SATU"]) if rtus["GI SATU"]["online"] else {
        "cb": "OFFLINE", "cb_closed": False, "trip": False, "uv": False, "ov": False
    }
    gd1 = gd_status(rtus["GD01"]) if rtus["GD01"]["online"] else {}
    gd2 = gd_status(rtus["GD02"]) if rtus["GD02"]["online"] else {}
    gd3 = gd_status(rtus["GD03"]) if rtus["GD03"]["online"] else {}
    gd4 = gd_status(rtus["GD04"]) if rtus["GD04"]["online"] else {}
    gd5 = gd_status(rtus["GD05"]) if rtus["GD05"]["online"] else {}
    gi2 = gi_status(rtus["GI DUA"]) if rtus["GI DUA"]["online"] else {
        "cb": "OFFLINE", "cb_closed": False, "trip": False, "uv": False, "ov": False
    }

    xs = [100, 230, 370, 510, 650, 790, 920]

    lines = []
    for seg in range(6):
        active_fault = (
            target == seg + 1
            and phase in (4, 5, 6, 8, 9)
        )
        lines.append(
            f'<line x1="{xs[seg]+42}" y1="150" '
            f'x2="{xs[seg+1]-42}" y2="150" '
            f'stroke="#94a3b8" stroke-width="2" stroke-dasharray="6,4"/>'
        )
        lines.append(
            draw_fault_icon(
                (xs[seg] + xs[seg+1]) // 2,
                150,
                active_fault,
            )
        )

    svg = f"""
    <svg width="100%" height="450"
         viewBox="0 0 1050 450"
         xmlns="http://www.w3.org/2000/svg"
         style="background:#0f172a;border-radius:10px;border:1px solid #334155;">
        <style>
            .blinking {{ animation: blink 1s linear infinite; }}
            @keyframes blink {{
                0% {{ opacity: 0; }}
                50% {{ opacity: 1; }}
                100% {{ opacity: 0; }}
            }}
        </style>

        {''.join(lines)}

        {draw_gi(100, "GI SATU", gi1["cb"],
                 fault=(gi1.get("trip", False) or gi1.get("uv", False)))}

        {draw_gd(230, "GD01",
                 gd1.get("lbs1", "OFFLINE"),
                 gd1.get("lbs2", "OFFLINE"),
                 gd1.get("current", 0),
                 fault=(target == 1 and phase in (4, 5, 6)),
                 hfd=gd1.get("hfd", False),
                 uv=gd1.get("uv", False),
                 ov=gd1.get("ov", False))}

        {draw_gd(370, "GD02",
                 gd2.get("lbs1", "OFFLINE"),
                 gd2.get("lbs2", "OFFLINE"),
                 gd2.get("current", 0),
                 fault=(target == 2 and phase in (4, 5, 6)),
                 hfd=gd2.get("hfd", False),
                 uv=gd2.get("uv", False),
                 ov=gd2.get("ov", False))}

        {draw_gd(510, "GD03",
                 gd3.get("lbs1", "OFFLINE"),
                 gd3.get("lbs2", "OFFLINE"),
                 gd3.get("current", 0),
                 fault=(target == 3 and phase in (4, 5, 6)),
                 is_nop=True,
                 hfd=gd3.get("hfd", False),
                 uv=gd3.get("uv", False),
                 ov=gd3.get("ov", False))}

        {draw_gd(650, "GD04",
                 gd4.get("lbs1", "OFFLINE"),
                 gd4.get("lbs2", "OFFLINE"),
                 gd4.get("current", 0),
                 fault=(target == 4 and phase in (4, 5, 6)),
                 hfd=gd4.get("hfd", False),
                 uv=gd4.get("uv", False),
                 ov=gd4.get("ov", False))}

        {draw_gd(790, "GD05",
                 gd5.get("lbs1", "OFFLINE"),
                 gd5.get("lbs2", "OFFLINE"),
                 gd5.get("current", 0),
                 fault=(target == 5 and phase in (4, 5, 6)),
                 hfd=gd5.get("hfd", False),
                 uv=gd5.get("uv", False),
                 ov=gd5.get("ov", False))}

        {draw_gi(920, "GI DUA", gi2["cb"],
                 fault=(gi2.get("trip", False) or gi2.get("uv", False)))}

        <text x="525" y="438" fill="#64748b" font-size="9"
              text-anchor="middle">
              Telemetri switch berasal dari RTU • Controller {HOST}:{CONTROLLER_PORT}
        </text>
    </svg>
    """

    return svg


# ============================================================
# SOE
# ============================================================

def read_soe(limit=15):
    if not SOE_FILE.exists():
        return []

    try:
        with open(SOE_FILE, "r", encoding="utf-8") as f:
            rows = [line.rstrip("\n") for line in f if line.strip()]
        return rows[-limit:]
    except OSError:
        return []


# ============================================================
# HEADER
# ============================================================

st.markdown(
    """
<div class="scada-header">
    <div>
        <div class="scada-title">⚡ Web SCADA - Live Distributed Grid FLISR</div>
        <div class="scada-sub">Supervisory control, fault localization, isolation & restoration</div>
    </div>
    <div class="live"><span class="dot"></span>LIVE</div>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# LOAD DATA
# ==============================================================

controller, controller_err = read_controller()
if controller_err:
    st.error(f"Controller: {controller_err}")
    st.stop()

rtus = read_rtus()
behavior, behavior_err = read_behavior()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("## 🎛️ HMI CONTROL")
    st.caption(f"Controller : {HOST}:{CONTROLLER_PORT}")
    st.caption(f"System Behavior : {HOST}:{SYSTEM_BEHAVIOR_PORT}")

    coils = controller["coils"]
    di = controller["di"]

    shg_enabled = bool(coils[CO_SHG_ENABLE]) if len(coils) > CO_SHG_ENABLE else False
    lockout = bool(di[DI_LOCKOUT]) if len(di) > DI_LOCKOUT else False

    st.markdown(
        f"**SHG:** {'🟢 ENABLED' if shg_enabled else '⚪ DISABLED'}"
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "ENABLE",
            width="stretch",
            disabled=shg_enabled,
        ):
            ok, msg = mb_write(
                CONTROLLER_PORT, "coil", CO_SHG_ENABLE, 1
            )
            if not ok:
                st.error(msg)
            else:
                st.rerun()

    with c2:
        if st.button(
            "DISABLE",
            width="stretch",
            disabled=not shg_enabled,
        ):
            ok, msg = mb_write(
                CONTROLLER_PORT, "coil", CO_SHG_ENABLE, 0
            )
            if not ok:
                st.error(msg)
            else:
                st.rerun()

    if st.button(
        "🔓 RESET LOCK-OUT",
        width="stretch",
        disabled=not lockout,
    ):
        ok, msg = mb_write(
            CONTROLLER_PORT, "coil", CO_RESET_LOCKOUT, 1
        )
        if not ok:
            st.error(msg)
        else:
            time.sleep(0.12)
            st.rerun()

    st.divider()

    st.markdown("## 🧪 FAULT SIMULATOR")
    st.markdown(
        """
        <div class="side-note">
        Tombol fault menulis ke <b>System Behavior :8027</b>.
        Controller tidak membaca port 8027.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if behavior_err:
        st.warning("8027 belum terhubung.")

    fault_cols = st.columns(2)

    for i, seg_name in enumerate(SEGMENT_NAMES):
        with fault_cols[i % 2]:
            if st.button(
                f"💥 K{i+1}",
                width="stretch",
                key=f"fault_{i+1}",
                disabled=(behavior_err is not None or not shg_enabled),
            ):
                ok1, msg1 = mb_write(
                    SYSTEM_BEHAVIOR_PORT, "hr", HR_MODE, 0
                )
                ok2, msg2 = mb_write(
                    SYSTEM_BEHAVIOR_PORT, "hr", HR_CASE, i + 1
                )
                if not ok1:
                    st.error(msg1)
                elif not ok2:
                    st.error(msg2)
                else:
                    time.sleep(0.15)
                    st.rerun()

    st.caption("Source fault: CB GI yang fault OPEN → NOP GD03-LBS2 CLOSE → suplai berpindah ke GI sehat.")

    s1, s2 = st.columns(2)

    with s1:
        if st.button(
            "⚡ GI SATU FAULT",
            width="stretch",
            disabled=(behavior_err is not None or not shg_enabled),
        ):
            mb_write(SYSTEM_BEHAVIOR_PORT, "hr", HR_MODE, 0)
            ok, msg = mb_write(
                SYSTEM_BEHAVIOR_PORT, "hr", HR_CASE, 7
            )
            if not ok:
                st.error(msg)
            else:
                time.sleep(0.15)
                st.rerun()

    with s2:
        if st.button(
            "⚡ GI DUA FAULT",
            width="stretch",
            disabled=(behavior_err is not None or not shg_enabled),
        ):
            mb_write(SYSTEM_BEHAVIOR_PORT, "hr", HR_MODE, 0)
            ok, msg = mb_write(
                SYSTEM_BEHAVIOR_PORT, "hr", HR_CASE, 8
            )
            if not ok:
                st.error(msg)
            else:
                time.sleep(0.15)
                st.rerun()

    if st.button(
        "🔄 REPAIR & CONTINUE",
        width="stretch",
        disabled=behavior_err is not None,
        help="Hapus fault injection dan lanjutkan pembacaan CSV. Topologi hasil healing dipertahankan.",
    ):
        ok, msg = mb_write(
            SYSTEM_BEHAVIOR_PORT, "hr", HR_REPAIR, 1
        )
        if not ok:
            st.error(msg)
        else:
            time.sleep(0.20)
            st.rerun()

    def reset_system_to_launch():
        results = []

        # Stop SHG first so the controller will not start a new action
        # while the topology is being normalized.
        results.append(("SHG DISABLE",) + mb_write(
            CONTROLLER_PORT, "coil", CO_SHG_ENABLE, 0
        ))

        # Clear controller lock-out latch if present.
        results.append(("RESET LOCK-OUT",) + mb_write(
            CONTROLLER_PORT, "coil", CO_RESET_LOCKOUT, 1
        ))

        # Clear fault injection first. The System Behavior process releases
        # the global CSV pause and clears the RTU injection registers.
        results.append(("CLEAR FAULT",) + mb_write(
            SYSTEM_BEHAVIOR_PORT, "hr", HR_REPAIR, 1
        ))

        # Give the asynchronous testbench a moment to clear its injection
        # before the controller performs the topology reset.
        time.sleep(0.30)

        # Controller-side test reset returns every switch to the exact
        # launch topology: both GI CB closed, all GD LBS closed except
        # GD03 LBS2 (NOP) open.
        results.append(("NORMALIZE TOPOLOGY",) + mb_write(
            CONTROLLER_PORT, "hr", HR_CONTROLLER_REPAIR, 1
        ))

        failed = [(name, msg) for name, ok, msg in results if not ok]
        if failed:
            for name, msg in failed:
                st.error(f"{name}: {msg}")
            return False

        # _repair_uji executes asynchronously inside controller.siklus.
        # Jangan hanya memeriksa DI_CONFIG_NORMAL yang mungkin masih stale;
        # verifikasi eksplisit kedua CB GI + seluruh 12 posisi launch.
        expected = [1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1]
        deadline = time.time() + 6.0
        while time.time() < deadline:
            status, err = mb_read(CONTROLLER_PORT, "di", 0, 64)
            if err is None and len(status) >= DI_SWITCH_BASE + 12:
                pos = [int(bool(v)) for v in status[DI_SWITCH_BASE:DI_SWITCH_BASE + 12]]
                normal = bool(status[DI_CONFIG_NORMAL])
                if normal and pos == expected:
                    return True
            time.sleep(0.20)

        st.warning(
            "Reset terkirim, tetapi posisi launch belum terkonfirmasi "
            "(terutama CB GI). Cek log controller/RTU."
        )
        return False

    st.divider()

    if st.button(
        "↩️ RESET SISTEM",
        type="primary",
        width="stretch",
        help="Kembalikan simulator ke kondisi awal launch: kedua GI CLOSE, semua LBS CLOSE kecuali NOP GD03-LBS2 OPEN, fault clear, dan SHG DISABLED.",
    ):
        if reset_system_to_launch():
            st.success("Sistem dikembalikan ke kondisi awal launch.")
            time.sleep(0.5)
            st.rerun()

    st.caption(
        "RESET SISTEM = kembali ke kondisi awal launch. REPAIR & CONTINUE = hanya menghapus fault dan melanjutkan CSV, topologi healing tetap dipertahankan."
    )

    st.divider()

    auto_refresh = st.checkbox(
        "🔄 Auto-Refresh",
        value=True,
        help="Refresh HMI setiap 1 detik.",
    )


# ============================================================
# STATUS
# ============================================================

ir = controller["ir"]
di = controller["di"]

phase = safe_int(ir[IR_PHASE])
target = safe_int(ir[IR_TARGET])
duration = safe_int(ir[IR_DURATION])
padam = safe_int(ir[IR_PADAM])
event_no = safe_int(ir[IR_EVENT])
rtu_online = safe_int(ir[IR_RTU_ONLINE])

active = bool(di[DI_SHG_ACTIVE])
in_progress = bool(di[DI_SHG_IN_PROGRESS])
incomplete = bool(di[DI_SHG_INCOMPLETE])
all_online = bool(di[DI_ALL_ONLINE])
config_normal = bool(di[DI_CONFIG_NORMAL])
lockout = bool(di[DI_LOCKOUT])


# ============================================================
# TOP METRICS
# ============================================================

st.markdown('<div class="section">📡 FLISR STATUS</div>', unsafe_allow_html=True)

m1, m2, m3, m4, m5, m6 = st.columns(6)

m1.metric("SHG", "ACTIVE" if active else "OFF")
m2.metric("PHASE", PHASE_NAME.get(phase, f"FASE {phase}"))
m3.metric(
    "TARGET",
    f"K{target}" if 1 <= target <= 6
    else "GI SATU" if target == 7
    else "GI DUA" if target == 8
    else "—",
)
m4.metric("GARDU PADAM", padam)
m5.metric("RTU ONLINE", f"{rtu_online}/7")
m6.metric("KEJADIAN", event_no)

chips = [
    (
        "🟢",
        "ALL RTU ONLINE",
        "ok" if all_online else "bad",
    ),
    (
        "🟢" if config_normal else "🟠",
        "CONFIG NORMAL" if config_normal else "CONFIG TIDAK NORMAL",
        "ok" if config_normal else "warn",
    ),
    (
        "🔴" if lockout else "🟢",
        "LOCK-OUT AKTIF" if lockout else "LOCK-OUT CLEAR",
        "bad" if lockout else "ok",
    ),
    (
        "🟠" if incomplete else "🟢",
        "INCOMPLETE" if incomplete else "COMPLETE",
        "warn" if incomplete else "ok",
    ),
    (
        "🔵" if in_progress else "⚪",
        "IN PROGRESS" if in_progress else "STANDBY",
        "warn" if in_progress else "ok",
    ),
]

st.markdown(
    '<div class="banner">' +
    "".join(
        f'<div class="chip {kind}">{icon}&nbsp;{html.escape(label)}</div>'
        for icon, label, kind in chips
    ) +
    "</div>",
    unsafe_allow_html=True,
)


# ============================================================
# EVENT SUMMARY
# ============================================================

st.markdown('<div class="section">🧭 EVENT SUMMARY</div>', unsafe_allow_html=True)

e1, e2, e3 = st.columns(3)

with e1:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-kicker">Current Phase</div>
            <div class="summary-value">{html.escape(PHASE_NAME.get(phase, f"FASE {phase}"))}</div>
            <div class="summary-note">{html.escape(PHASE_DESC.get(phase, ""))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with e2:
    target_text = (
        f"K{target} · {SEGMENT_NAMES[target-1]}"
        if 1 <= target <= 6
        else "Sumber GI SATU"
        if target == 7
        else "Sumber GI DUA"
        if target == 8
        else "Tidak ada"
    )

    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-kicker">Target</div>
            <div class="summary-value">{html.escape(target_text)}</div>
            <div class="summary-note">Event counter #{event_no}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with e3:
    st.markdown(
        f"""
        <div class="summary-card">
            <div class="summary-kicker">Last Handling Time</div>
            <div class="summary-value">{duration/1000:.3f} s</div>
            <div class="summary-note">Gardu masih padam · {padam}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# SLD
# ============================================================

st.markdown(
    '<div class="section">🖥️ Live Single Line Diagram</div>',
    unsafe_allow_html=True,
)

st.iframe(
    build_sld(rtus, controller),
    height=450,
    width="stretch",
)


# ============================================================
# NODE HEALTH
# ============================================================

st.markdown('<div class="section">🧩 Node Health</div>', unsafe_allow_html=True)

node_cols = st.columns(7)

for idx, (name, port) in enumerate(RTU_PORTS.items()):
    info = rtus[name]
    online = info["online"]

    with node_cols[idx]:
        if online:
            badge_color = "#0d8a55"
            badge_bg = "#e8f8ef"
            state = "ONLINE"
        else:
            badge_color = "#b42334"
            badge_bg = "#ffecee"
            state = "OFFLINE"

        st.markdown(
            f"""
            <div style="
                background:#ffffff;
                border:1px solid #d9dfe8;
                border-radius:11px;
                padding:10px;
                min-height:92px;">
                <div style="font-size:13px;font-weight:800;color:#172033;">
                    {"🟢" if online else "🔴"} {html.escape(name)}
                </div>
                <div class="small-muted">127.0.0.1:{port}</div>
                <div style="
                    margin-top:8px;
                    display:inline-block;
                    padding:4px 8px;
                    border-radius:999px;
                    color:{badge_color};
                    background:{badge_bg};
                    font-size:10px;
                    font-weight:800;">
                    {state}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# ============================================================
# TELEMETRI RTU
# ============================================================

st.markdown('<div class="section">📊 Telemetri RTU</div>', unsafe_allow_html=True)

telemetry_rows = []

for name, info in rtus.items():
    if not info["online"]:
        telemetry_rows.append(
            {
                "Node": name,
                "Online": "NO",
                "Status": "OFFLINE",
                "Tegangan (V)": 0,
                "Arus (A)": 0,
            }
        )
        continue

    if name.startswith("GI"):
        s = gi_status(info)
        status = s["cb"]
        if s["trip"]:
            status = "TRIP"
        elif s["uv"]:
            status = "UV"
        elif s["ov"]:
            status = "OV"

        telemetry_rows.append(
            {
                "Node": name,
                "Online": "YES",
                "Status": status,
                "Tegangan (V)": s["voltage"],
                "Arus (A)": s["current"],
            }
        )
    else:
        s = gd_status(info)
        status = "AMAN"
        if s["hfd"]:
            status = "HFD"
        elif s["uv"]:
            status = "UV"
        elif s["ov"]:
            status = "OV"

        telemetry_rows.append(
            {
                "Node": name,
                "Online": "YES",
                "Status": status,
                "Tegangan (V)": s["voltage"],
                "Arus (A)": s["current"],
            }
        )

st.dataframe(
    telemetry_rows,
    hide_index=True,
    width="stretch",
)


# ============================================================
# SOE
# ============================================================

st.markdown(
    '<div class="section">🧾 Sequence of Events</div>',
    unsafe_allow_html=True,
)

soe = read_soe(18)

if soe:
    st.code("\n".join(soe), language="text")
else:
    st.info("Belum ada event pada soe.csv.")


# ============================================================
# FOOTER / REFRESH
# ============================================================

behavior_text = (
    f"Case {behavior['case']} · "
    f"Mode {'MANUAL' if behavior['mode'] == 0 else 'ONLINE'}"
    if behavior is not None
    else "System Behavior offline"
)

st.caption(
    f"Controller {HOST}:{CONTROLLER_PORT} · "
    f"{behavior_text} · "
    f"Refresh {time.strftime('%H:%M:%S')}"
)

if auto_refresh:
    time.sleep(1.0)
    st.rerun()
