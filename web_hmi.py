import csv
import html
import os
import time
from pathlib import Path

import streamlit as st
from pymodbus.client import ModbusTcpClient

import topologi as T


# ============================================================
# KONFIGURASI

HOST = T.HOST_SIMULATOR           # PC physical Ethernet alias on S1
CONTROLLER_PORT = T.PORT_SHG      # 502 on 192.168.250.2
SYSTEM_BEHAVIOR_PORT = T.PORT_TESTBENCH  # 503 on 192.168.250.2
WEB_PORT = T.PORT_WEB_HMI         # 8501 on 192.168.250.2
SLAVE_ID = T.SLAVE_RTU
FLISR_MODE = os.getenv("FLISR_MODE", "N").strip().upper()
if FLISR_MODE not in {"N", "Y"}:
    FLISR_MODE = "N"
HUE_RESET_MAP_ENABLED = T.HUE_RESET_SOURCE_MAP_AVAILABLE

# These are stable logical IDs retained by the UI, NOT actual TCP ports.
# Mode N resolves status/commands directly to each simulator. Mode Y resolves
# the RTU CS image and commands through the HUe CHFLISR server; analog telemetry
# is still read from simulator IR because no analog points are mapped in CoreDb.
RTU_PORTS = {
    "GI SATU": 8020,
    "GD01": 8021,
    "GD02": 8022,
    "GD03": 8023,
    "GD04": 8024,
    "GD05": 8025,
    "GI DUA": 8026,
}


def resolve_modbus_endpoint(logical_port, simulator=False):
    """Resolve a logical RTU ID to the active status/command endpoint.

    simulator=True bypasses the HUe gateway and is reserved for simulator-only
    controls (selector HRs and analog test telemetry).
    """
    if logical_port in T.RTU_ID_TO_NODE:
        if FLISR_MODE == "Y" and not simulator:
            return T.HOST_HUE_MODBUS, T.PORT_HUE_MODBUS
        return T.endpoint_logical_id(logical_port)
    return HOST, int(logical_port)


def resolve_modbus_unit_id(logical_port, simulator=False):
    if logical_port in T.RTU_ID_TO_NODE and FLISR_MODE == "Y" and not simulator:
        return T.hue_unit_id(T.RTU_ID_TO_NODE[logical_port])
    return SLAVE_ID

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
CONTROLLER_DI_COUNT = 88

# Controller selector feedback: 12 local bits followed by 12 remote bits.
DI_LR_LOCAL_BASE = 64
DI_LR_REMOTE_BASE = 76

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

# System Behavior 503 HR
HR_CASE = 0
HR_MODE = 1
HR_REPAIR = 2
HR_TRIGGER = 3       # increment on every fault-button click
HR_APPLIED = 4       # sequence number acknowledged by System Behavior
HR_STATUS = 5        # 0 idle, 1 verified, 2 partial, 3 not ready, 4 error

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

THEMES = {
    "light": {
        "bg": "#eef1f5", "card": "#ffffff", "border": "#d9dfe8",
        "sidebar": "#e9edf2", "sidebar_border": "#d6dce5",
        "text": "#172033", "muted": "#66748a",
        "chip_bg": "#f3f5f8", "chip_border": "#d8dee8", "chip_text": "#49566b",
        "ok_bg": "#e8f8ef", "ok_border": "#bfe9d1", "ok_text": "#0c8a55",
        "warn_bg": "#fff6df", "warn_border": "#f0dfab", "warn_text": "#9b6a00",
        "bad_bg": "#ffecee", "bad_border": "#efc1c9", "bad_text": "#b42334",
        "info_bg": "#e6f0ff", "info_border": "#bcd3f7", "info_text": "#1d5fc4",
        "note_bg": "#f7f9fb", "note_border": "#cbd4df",
        "btn_bg": "#ffffff", "btn_border": "#cdd5e1", "btn_hover": "#8391a5",
        "live_bg": "#e7f8ef", "live_border": "#bdebd3", "live_text": "#0d8a55",
        "shadow": "rgba(15, 23, 42, 0.06)",
        "code_bg": "#f3f5f8", "table_head": "#f3f5f8", "table_line": "#e6ebf2",
        "sld_bg": "#ffffff", "sld_border": "#d9dfe8",
        "sld_text": "#172033", "sld_sub": "#66748a",
        "sld_on": "#10b981", "sld_off": "#b6c0cf", "sld_fault": "#dc2626",
        "sld_box": "#f1f5f9", "sld_box_border": "#cbd5e1", "sld_readout": "#0369a1",
    },
    "dark": {
        "bg": "#0b1220", "card": "#151e30", "border": "#27344a",
        "sidebar": "#101828", "sidebar_border": "#27344a",
        "text": "#e6ebf5", "muted": "#93a1b8",
        "chip_bg": "#1c2840", "chip_border": "#2c3b57", "chip_text": "#b7c3d8",
        "ok_bg": "#0f2b20", "ok_border": "#1b5a3f", "ok_text": "#4ade9b",
        "warn_bg": "#2f2610", "warn_border": "#5c4a17", "warn_text": "#f5c24d",
        "bad_bg": "#331519", "bad_border": "#6b2530", "bad_text": "#ff7d8c",
        "info_bg": "#10243f", "info_border": "#24456f", "info_text": "#6db3ff",
        "note_bg": "#1a2438", "note_border": "#3a4a66",
        "btn_bg": "#1c2840", "btn_border": "#34445f", "btn_hover": "#6b7f9e",
        "live_bg": "#0f2b20", "live_border": "#1b5a3f", "live_text": "#4ade9b",
        "shadow": "rgba(0, 0, 0, 0.35)",
        "code_bg": "#0f1626", "table_head": "#1c2840", "table_line": "#27344a",
        "sld_bg": "#0f172a", "sld_border": "#334155",
        "sld_text": "#f1f5f9", "sld_sub": "#94a3b8",
        "sld_on": "#34d399", "sld_off": "#475569", "sld_fault": "#ef4444",
        "sld_box": "#020617", "sld_box_border": "#334155", "sld_readout": "#00e5ff",
    },
}

# Tema mengikuti pilihan di menu Settings Streamlit (System/Light/Dark).
# Streamlit men-set `color-scheme` pada .stApp, dan light-dark() memilih nilai
# yang sesuai secara langsung di browser, tanpa perlu rerun dari Python.
_theme_vars = "\n".join(
    f"    --{key.replace('_', '-')}: light-dark({THEMES['light'][key]}, {THEMES['dark'][key]});"
    for key in THEMES["light"]
)

THEME_CSS = """
<style>
:root {
__VARS__
}

html, body, .stApp, [data-testid="stAppViewContainer"] {
    background: var(--bg);
    color: var(--text);
}

[data-testid="stHeader"] {
    background: var(--bg);
}

[data-testid="stToolbar"] * {
    color: var(--muted) !important;
}

.block-container,
[data-testid="stMainBlockContainer"] {
    max-width: 1720px !important;
    padding-top: 4.5rem !important;
    padding-bottom: 2.5rem !important;
}

[data-testid="stSidebar"] {
    background: var(--sidebar);
    border-right: 1px solid var(--sidebar-border);
}

/* Rapatkan bagian atas sidebar (header + padding bawaan terlalu tinggi) */
[data-testid="stSidebarHeader"] {
    height: auto !important;
    min-height: 0 !important;
    padding: 0.5rem 0.75rem 0 !important;
    margin-bottom: 0 !important;
}

[data-testid="stSidebarUserContent"] {
    padding-top: 0 !important;
}

[data-testid="stSidebarUserContent"] h2:first-of-type {
    padding-top: 0 !important;
    margin-top: 0 !important;
}

h1, h2, h3, h4,
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: var(--text) !important;
}

[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] * {
    color: var(--muted) !important;
}

hr {
    border-color: var(--border) !important;
}

[data-testid="stMetric"] {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 14px;
    box-shadow: 0 1px 5px var(--shadow);
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] * {
    color: var(--muted) !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] * {
    color: var(--text) !important;
    font-weight: 750;
}

.stButton > button,
[data-testid="stBaseButton-secondary"] {
    border-radius: 9px;
    min-height: 40px;
    font-weight: 650;
    border: 1px solid var(--btn-border);
    background: var(--btn-bg);
    color: var(--text);
}

.stButton > button:hover,
[data-testid="stBaseButton-secondary"]:hover {
    border-color: var(--btn-hover);
    color: var(--text);
}

.stButton > button:disabled,
[data-testid="stBaseButton-secondary"]:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    border-color: var(--btn-border);
}

[data-testid="stBaseButton-primary"] {
    border-radius: 9px;
    min-height: 40px;
    font-weight: 650;
}

[data-testid="stCode"] pre,
[data-testid="stCode"] code {
    background: var(--code-bg) !important;
    color: var(--text) !important;
}

.scada-header {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:20px;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:14px;
    padding:15px 18px;
    margin-bottom:12px;
    box-shadow:0 2px 8px var(--shadow);
}

.scada-title {
    font-size:24px;
    font-weight:800;
    color:var(--text);
}

.scada-sub {
    color:var(--muted);
    font-size:12px;
    margin-top:2px;
}

.live {
    color:var(--live-text);
    font-size:12px;
    font-weight:750;
    background:var(--live-bg);
    border:1px solid var(--live-border);
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
    color:var(--text);
    font-size:17px;
    font-weight:800;
    margin:16px 0 8px;
}

.banner {
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    padding:9px 11px;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:11px;
}

.chip {
    border-radius:999px;
    padding:5px 9px;
    font-size:11px;
    font-weight:700;
    background:var(--chip-bg);
    border:1px solid var(--chip-border);
    color:var(--chip-text);
}

.chip.ok { background:var(--ok-bg); border-color:var(--ok-border); color:var(--ok-text); }
.chip.warn { background:var(--warn-bg); border-color:var(--warn-border); color:var(--warn-text); }
.chip.bad { background:var(--bad-bg); border-color:var(--bad-border); color:var(--bad-text); }

.summary-card {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:12px;
    padding:14px 15px;
    min-height:112px;
    box-shadow:0 1px 5px var(--shadow);
}

.summary-kicker {
    color:var(--muted);
    font-size:10px;
    text-transform:uppercase;
    letter-spacing:.08em;
}

.summary-value {
    color:var(--text);
    font-size:18px;
    font-weight:800;
    margin-top:5px;
}

.summary-note {
    color:var(--muted);
    font-size:11px;
    margin-top:4px;
}

.side-note {
    background:var(--note-bg);
    border:1px dashed var(--note-border);
    border-radius:10px;
    padding:9px 10px;
    color:var(--muted);
    font-size:11px;
    line-height:1.4;
}

.small-muted {
    color:var(--muted);
    font-size:11px;
}

.node-card {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:11px;
    padding:10px;
    min-height:92px;
}

.node-name {
    font-size:13px;
    font-weight:800;
    color:var(--text);
}

.node-badge {
    margin-top:8px;
    display:inline-block;
    padding:4px 8px;
    border-radius:999px;
    font-size:10px;
    font-weight:800;
}

.node-badge.ok { background:var(--ok-bg); color:var(--ok-text); }
.node-badge.bad { background:var(--bad-bg); color:var(--bad-text); }

.tbl {
    width:100%;
    border-collapse:collapse;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:12px;
    overflow:hidden;
    font-size:13px;
}

.tbl th {
    background:var(--table-head);
    color:var(--muted);
    text-align:left;
    padding:9px 12px;
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:.06em;
}

.tbl td {
    color:var(--text);
    padding:9px 12px;
    border-top:1px solid var(--table-line);
}

.alert {
    display:flex;
    align-items:center;
    gap:14px;
    border-radius:14px;
    padding:14px 18px;
    margin-bottom:12px;
    border:1px solid;
}

.alert.crit {
    background:var(--bad-bg);
    border-color:var(--bad-border);
    color:var(--bad-text);
    animation:alertpulse 1.6s ease-in-out infinite;
}

.alert.warn {
    background:var(--warn-bg);
    border-color:var(--warn-border);
    color:var(--warn-text);
}

.alert-icon { font-size:26px; line-height:1; }
.alert-title { font-size:16px; font-weight:800; letter-spacing:.02em; }
.alert-sub { font-size:12px; opacity:.85; margin-top:2px; }

@keyframes alertpulse {
    0%, 100% { box-shadow:0 0 0 0 rgba(239,68,68,0); }
    50% { box-shadow:0 0 0 5px rgba(239,68,68,.22); }
}

.stepper {
    display:flex;
    align-items:center;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:12px;
    padding:16px 22px;
}

.step {
    display:flex;
    flex-direction:column;
    align-items:center;
    gap:6px;
    min-width:86px;
}

.step-dot {
    width:32px;
    height:32px;
    border-radius:50%;
    display:flex;
    align-items:center;
    justify-content:center;
    font-weight:800;
    font-size:14px;
    background:var(--chip-bg);
    border:2px solid var(--chip-border);
    color:var(--muted);
}

.step-label { font-size:12px; font-weight:700; color:var(--muted); }

.step.done .step-dot {
    background:var(--ok-text);
    border-color:var(--ok-text);
    color:var(--card);
}
.step.done .step-label { color:var(--ok-text); }

.step.active .step-dot {
    background:var(--warn-bg);
    border-color:var(--warn-text);
    color:var(--warn-text);
    animation:alertpulse 1.6s ease-in-out infinite;
}
.step.active .step-label { color:var(--warn-text); }

.step.partial .step-dot {
    background:var(--warn-text);
    border-color:var(--warn-text);
    color:var(--card);
}
.step.partial .step-label { color:var(--warn-text); }

.step-line {
    flex:1;
    height:3px;
    border-radius:2px;
    background:var(--chip-border);
    margin:0 6px 22px;
}
.step-line.done { background:var(--ok-text); }

.stepper-note { color:var(--muted); font-size:12px; margin:8px 2px 0; }

.section-note {
    margin-left:10px;
    color:var(--muted);
    font-size:12px;
    font-weight:600;
}

.tbl-wrap {
    max-height:430px;
    overflow:auto;
    border:1px solid var(--border);
    border-radius:12px;
    background:var(--card);
    margin-bottom:10px;
}

.tbl-wrap .tbl { border:none; border-radius:0; }

.tbl-wrap .tbl th {
    position:sticky;
    top:0;
    z-index:1;
}

.tbl .mono { font-family:Consolas, "Courier New", monospace; white-space:nowrap; }
.tbl .num { text-align:right; }

.soe tbody tr:hover td { background:var(--chip-bg); }

.soe-time { color:var(--text); font-weight:700; margin-right:8px; }
.soe-date { color:var(--muted); font-size:11px; }
.soe-desc { width:100%; }

.pill {
    display:inline-block;
    min-width:84px;
    text-align:center;
    padding:3px 9px;
    border-radius:999px;
    border:1px solid var(--chip-border);
    background:var(--chip-bg);
    color:var(--chip-text);
    font-size:10px;
    font-weight:800;
    letter-spacing:.04em;
}
.pill.ok { background:var(--ok-bg); border-color:var(--ok-border); color:var(--ok-text); }
.pill.warn { background:var(--warn-bg); border-color:var(--warn-border); color:var(--warn-text); }
.pill.bad { background:var(--bad-bg); border-color:var(--bad-border); color:var(--bad-text); }
.pill.info { background:var(--info-bg); border-color:var(--info-border); color:var(--info-text); }

.empty-state {
    background:var(--card);
    border:1px dashed var(--border);
    border-radius:12px;
    padding:22px;
    text-align:center;
    color:var(--muted);
    font-size:13px;
}

svg.sld { display:block; }
.blinking { animation: blink 1s linear infinite; }
.flow {
    stroke-dasharray: 2 12;
    animation: flow 1.2s linear infinite;
}
@keyframes blink {
    0% { opacity: 0.1; }
    50% { opacity: 1; }
    100% { opacity: 0.1; }
}
@keyframes flow {
    to { stroke-dashoffset: -14; }
}
</style>
""".replace("__VARS__", _theme_vars)

st.markdown(THEME_CSS, unsafe_allow_html=True)


# ============================================================
# MODBUS HELPERS
# ============================================================

def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def mb_read(port, point_type, address, count, simulator=False):
    target_host, target_port = resolve_modbus_endpoint(port, simulator=simulator)
    target_unit = resolve_modbus_unit_id(port, simulator=simulator)
    client = ModbusTcpClient(target_host, port=target_port, timeout=1.2)
    if not client.connect():
        return None, f"Endpoint {target_host}:{target_port} (ID {port}) tidak dapat dihubungi."

    try:
        if point_type == "di":
            response = client.read_discrete_inputs(
                address, count, slave=target_unit
            )
            values = list(getattr(response, "bits", []) or [])
        elif point_type == "co":
            response = client.read_coils(
                address, count, slave=target_unit
            )
            values = list(getattr(response, "bits", []) or [])
        elif point_type == "ir":
            response = client.read_input_registers(
                address, count, slave=target_unit
            )
            values = list(getattr(response, "registers", []) or [])
        elif point_type == "hr":
            response = client.read_holding_registers(
                address, count, slave=target_unit
            )
            values = list(getattr(response, "registers", []) or [])
        else:
            return None, "Tipe register tidak dikenal."

        if response is None or response.isError():
            return None, f"Modbus error {target_host}:{target_port} (ID {port}) -> {response}"

        return values, None
    except Exception as exc:
        return None, str(exc)
    finally:
        client.close()


def mb_write(port, point_type, address, value, simulator=False):
    target_host, target_port = resolve_modbus_endpoint(port, simulator=simulator)
    target_unit = resolve_modbus_unit_id(port, simulator=simulator)
    client = ModbusTcpClient(target_host, port=target_port, timeout=1.2)
    if not client.connect():
        return False, f"Endpoint {target_host}:{target_port} (ID {port}) tidak dapat dihubungi."

    try:
        if point_type == "coil":
            response = client.write_coil(
                address, bool(value), slave=target_unit
            )
        elif point_type == "hr":
            response = client.write_register(
                address, int(value), slave=target_unit
            )
        else:
            return False, "Jenis write tidak dikenal."

        if response is None or response.isError():
            return False, f"Modbus write gagal {target_host}:{target_port} (ID {port}) -> {response}"

        return True, None
    except Exception as exc:
        return False, str(exc)
    finally:
        client.close()


def read_controller():
    co, err = mb_read(CONTROLLER_PORT, "co", 0, 2)
    if err:
        return None, err

    di, err = mb_read(CONTROLLER_PORT, "di", 0, CONTROLLER_DI_COUNT)
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
    """Read RTU feedback as FC01 CS points; analog IR is simulator telemetry.

    In Mode Y, FC01 feedback is acquired from CHFLISR on the HUe using logical
    Unit IDs 1..7. In Mode N, the same CS image is read from each simulator IP.
    IR telemetry is read directly from the simulator because the current HUe
    CoreDb Analog table does not expose current/voltage points to CHFLISR.
    """
    result = {}
    for name, logical_id in RTU_PORTS.items():
        node = T.RTU_ID_TO_NODE[logical_id]
        cs_count = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
        cs, cs_error = mb_read(logical_id, "co", 0, cs_count)
        ir, ir_error = mb_read(logical_id, "ir", 0, 3, simulator=True)

        if cs_error:
            result[name] = {
                "online": False, "cs": [], "ir": [],
                "error": cs_error, "telemetry_error": ir_error,
            }
        else:
            result[name] = {
                "online": True, "cs": cs, "ir": ir or [],
                "error": None, "telemetry_error": ir_error,
            }
    return result


# Each selector is emulated by a dedicated Holding Register on the RTU.
# Value 0=LOCAL, 1=REMOTE. These are simulator controls, not physical I/O.
LR_SWITCHES = [
    {"key": "gi1_cb", "label": "GI SATU · CB", "rtu": "GI SATU", "port": 8020,
     "hr": 4, "local_cs": 3, "remote_cs": 4},
]
for _gd in range(1, 6):
    _name = f"GD{_gd:02d}"
    _port = 8020 + _gd
    LR_SWITCHES.append({"key": f"gd{_gd:02d}_lbs1", "label": f"{_name} · LBS1", "rtu": _name,
                        "port": _port, "hr": 5, "local_cs": 3, "remote_cs": 4})
    LR_SWITCHES.append({"key": f"gd{_gd:02d}_lbs2", "label": f"{_name} · LBS2", "rtu": _name,
                        "port": _port, "hr": 6, "local_cs": 8, "remote_cs": 9})
LR_SWITCHES.append({"key": "gi2_cb", "label": "GI DUA · CB", "rtu": "GI DUA", "port": 8026,
                    "hr": 4, "local_cs": 3, "remote_cs": 4})


def selector_state(info, local_index, remote_index):
    if not info or not info.get("online"):
        return "OFFLINE"
    bits = info.get("cs", [])
    if len(bits) <= max(local_index, remote_index):
        return "NO FEEDBACK"
    local_bit = int(bool(bits[local_index]))
    remote_bit = int(bool(bits[remote_index]))
    if (local_bit, remote_bit) == (1, 0):
        return "LOCAL"
    if (local_bit, remote_bit) == (0, 1):
        return "REMOTE"
    if (local_bit, remote_bit) == (0, 0):
        return "NO FEEDBACK"
    return "INVALID"


def read_behavior():
    hr, err = mb_read(SYSTEM_BEHAVIOR_PORT, "hr", 0, 6)
    if err:
        return None, err

    return {
        "case": safe_int(hr[HR_CASE]) if len(hr) > HR_CASE else 0,
        "mode": safe_int(hr[HR_MODE]) if len(hr) > HR_MODE else 0,
        "repair": safe_int(hr[HR_REPAIR]) if len(hr) > HR_REPAIR else 0,
        "trigger": safe_int(hr[HR_TRIGGER]) if len(hr) > HR_TRIGGER else 0,
        "applied": safe_int(hr[HR_APPLIED]) if len(hr) > HR_APPLIED else 0,
        "status": safe_int(hr[HR_STATUS]) if len(hr) > HR_STATUS else 0,
    }, None


def submit_fault_case(case):
    """Submit a fault case with a sequence handshake; same K can be pressed again."""
    for addr, value, label in (
        (HR_MODE, 0, "mode"),
        (HR_CASE, int(case), "case"),
    ):
        ok, msg = mb_write(SYSTEM_BEHAVIOR_PORT, "hr", addr, value)
        if not ok:
            return False, f"Gagal mengirim {label}: {msg}"

    seqs, err = mb_read(SYSTEM_BEHAVIOR_PORT, "hr", HR_TRIGGER, 2)
    if err or not seqs or len(seqs) < 2:
        return False, f"Gagal membaca trigger/ack Testbench: {err or 'respons tidak lengkap'}"
    current_trigger, current_applied = map(safe_int, seqs[:2])

    # If a previous request is still being processed, don't overwrite it.
    wait_deadline = time.monotonic() + 8.0
    while current_trigger != current_applied and time.monotonic() < wait_deadline:
        time.sleep(0.1)
        seqs, err = mb_read(SYSTEM_BEHAVIOR_PORT, "hr", HR_TRIGGER, 2)
        if not err and seqs and len(seqs) >= 2:
            current_trigger, current_applied = map(safe_int, seqs[:2])
    if current_trigger != current_applied:
        return False, "Testbench masih memproses fault sebelumnya. Tunggu selesai sebelum menekan kasus baru."

    sequence = 1 if current_trigger >= 65535 else current_trigger + 1
    ok, msg = mb_write(SYSTEM_BEHAVIOR_PORT, "hr", HR_TRIGGER, sequence)
    if not ok:
        return False, f"Gagal mengirim trigger fault case: {msg}"

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        result, err = mb_read(SYSTEM_BEHAVIOR_PORT, "hr", HR_APPLIED, 2)
        if not err and result and len(result) >= 2 and safe_int(result[0]) == sequence:
            status = safe_int(result[1])
            if status == 1:
                return True, f"K{case}: pola RTU berhasil diterapkan dan diverifikasi sebelum Controller melanjutkan."
            if status == 2:
                return False, f"K{case}: pola HFD tidak cocok pada readback. Lihat log System Behavior untuk RTU yang gagal."
            if status == 3:
                return False, "Fault ditolak: Controller harus dalam fase SIAGA dan tidak sedang menangani gangguan. Gunakan RESET SISTEM, aktifkan SHG, lalu tunggu SIAGA."
            return False, "System Behavior gagal menyiapkan fault. Periksa koneksi tujuh RTU dan log System Behavior."
        time.sleep(0.1)
    return False, f"Timeout menunggu acknowledgement dari System Behavior untuk K{case}. Periksa log Testbench."


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
    cs = info.get("cs", [])
    lbs1_name, lbs1_closed, lbs1_valid = dp_status(cs, 2, 1)
    lbs2_name, lbs2_closed, lbs2_valid = dp_status(cs, 7, 6)

    hfd1 = bool(cs[0]) if len(cs) > 0 else False
    hfd2 = bool(cs[5]) if len(cs) > 5 else False
    hfd = hfd1 or hfd2
    current = safe_int(info["ir"][0]) if len(info.get("ir", [])) > 0 else 0
    voltage = safe_int(info["ir"][2]) if len(info.get("ir", [])) > 2 else 0
    uv = 0 < voltage < 18_000
    ov = voltage > 22_000

    return {
        "lbs1": lbs1_name, "lbs1_closed": lbs1_closed, "lbs1_valid": lbs1_valid,
        "lbs2": lbs2_name, "lbs2_closed": lbs2_closed, "lbs2_valid": lbs2_valid,
        "hfd1": hfd1, "hfd2": hfd2, "hfd": hfd, "uv": uv, "ov": ov,
        "current": current, "voltage": voltage,
    }


def gi_status(info):
    cs = info.get("cs", [])
    cb_name, cb_closed, cb_valid = dp_status(cs, 2, 1)
    trip = bool(cs[0]) if len(cs) > 0 else False
    current = safe_int(info["ir"][0]) if len(info.get("ir", [])) > 0 else 0
    voltage = safe_int(info["ir"][2]) if len(info.get("ir", [])) > 2 else 0
    uv = (bool(cs[5]) if len(cs) > 5 else False) or (0 < voltage < 18_000)
    ov = voltage > 22_000

    return {
        "cb": cb_name, "cb_closed": cb_closed, "cb_valid": cb_valid,
        "trip": trip, "uv": uv, "ov": ov,
        "current": current, "voltage": voltage,
    }


def _wait_rtu_switch_feedback(logical_port, bay, closed, timeout=None):
    """Confirm position from the active CS feedback endpoint after a command."""
    node = T.RTU_ID_TO_NODE[logical_port]
    count = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
    if timeout is None:
        timeout = T.HUE_FEEDBACK_TIMEOUT_SECONDS if FLISR_MODE == "Y" else 2.0
    if T.adalah_gardu_induk(node):
        open_idx, close_idx = T.DI_CB_BUKA, T.DI_CB_TUTUP
    elif bay == 0:
        open_idx, close_idx = T.DI_GD_LBS1_OPEN, T.DI_GD_LBS1_CLOSE
    else:
        open_idx, close_idx = T.DI_GD_LBS2_OPEN, T.DI_GD_LBS2_CLOSE
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        bits, error = mb_read(logical_port, "co", 0, count)
        if not error and bits and len(bits) > max(open_idx, close_idx):
            if bool(bits[close_idx]) == bool(closed) and bool(bits[open_idx]) == (not bool(closed)):
                return True, None
        time.sleep(0.10)
    action = "CLOSE" if closed else "OPEN"
    return False, f"Perintah {action} terkirim, tetapi feedback CS belum mengonfirmasi posisi target."


def send_manual_switch(logical_port, bay, closed):
    """Send a mode-aware manual switching command with readback verification."""
    node = T.RTU_ID_TO_NODE[logical_port]
    action = "CLOSE" if closed else "OPEN"
    if FLISR_MODE == "Y":
        address = T.hue_switch_command_address(node, bay, bool(closed))
        ok, error = mb_write(logical_port, "coil", address, True)
        if not ok:
            return False, f"Gagal mengirim {action} melalui HUe: {error}"
        time.sleep(T.HUE_CMD_PULSE_SECONDS)
        clear_ok, clear_error = mb_write(logical_port, "coil", address, False)
        if not clear_ok:
            # Best-effort clear so a transient response error does not leave
            # a command-source coil asserted indefinitely.
            mb_write(logical_port, "coil", address, False)
            return False, f"Perintah {action} terkirim tetapi pulse CHFLISR gagal dilepas: {clear_error}"
    else:
        address = T.CO_PERINTAH + bay
        ok, error = mb_write(logical_port, "coil", address, bool(closed), simulator=True)
        if not ok:
            return False, f"Gagal mengirim {action} ke simulator: {error}"
    verified, verify_error = _wait_rtu_switch_feedback(logical_port, bay, bool(closed))
    if not verified:
        return False, verify_error
    return True, f"{action} terkonfirmasi dari feedback FC01."


def send_protection_reset(logical_port):
    """Reset GI trip or both GD HFD latches using the selected communication path."""
    node = T.RTU_ID_TO_NODE[logical_port]
    if FLISR_MODE == "N":
        ok, error = mb_write(logical_port, "coil", T.CO_RESET, True, simulator=True)
        if not ok:
            return False, f"Reset simulator gagal: {error}"
    else:
        if not HUE_RESET_MAP_ENABLED:
            return False, (
                "Reset HUe masih dikunci. Kirim NEWEST_FLISR_Reset_Mapped.ebc "
                "ke HUe, verifikasi source CS6/CS10/CS11, lalu aktifkan "
                "FLISR_HUE_RESET_MAP=1 saat startup."
            )
        for address in T.hue_reset_source_addresses(node):
            ok, error = mb_write(logical_port, "coil", address, True)
            if not ok:
                return False, f"Reset melalui HUe gagal pada CS:{address}: {error}"
            time.sleep(T.HUE_CMD_PULSE_SECONDS)
            cleared, clear_error = mb_write(logical_port, "coil", address, False)
            if not cleared:
                mb_write(logical_port, "coil", address, False)
                return False, f"Reset terkirim tetapi pulse CS:{address} gagal dilepas: {clear_error}"

    count = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
    reset_indices = [T.DI_CB_TRIP] if T.adalah_gardu_induk(node) else [T.DI_GD_LBS1_HFD, T.DI_GD_LBS2_HFD]
    deadline = time.monotonic() + T.HUE_FEEDBACK_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        bits, error = mb_read(logical_port, "co", 0, count)
        if not error and all(index < len(bits) and not bool(bits[index]) for index in reset_indices):
            return True, "Reset terkonfirmasi: feedback trip/HFD sudah CLEAR."
        time.sleep(0.10)
    return False, "Reset terkirim tetapi feedback trip/HFD belum CLEAR. Periksa latch RTU dan pemetaan CoreDb."


# ============================================================
# SVG COMPONENTS
# ============================================================

# Warna SLD memakai CSS variable (lihat THEMES) sehingga ikut berganti tema.
SLD = {
    key: f"var(--sld-{key.replace('_', '-')})"
    for key in (
        "bg", "border", "text", "sub", "on", "off", "fault",
        "box", "box_border", "readout",
    )
}

SWITCH_COLOR = {
    "CLOSE": "#10b981",
    "OPEN": "#ef4444",
    "TRANSIT": "#f59e0b",
}


def sld_wire(x1, y1, x2, y2, color, width=3):
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
    )


def draw_lbs(x, y, status, label, ext_color, bus_color):
    color = SWITCH_COLOR.get(status, "#64748b")

    if status == "CLOSE":
        blade = f"M {x} {y+10} L {x} {y+30}"
    elif status == "OPEN":
        blade = f"M {x} {y+10} L {x+12} {y+25}"
    elif status == "TRANSIT":
        blade = f"M {x} {y+10} L {x+7} {y+20}"
    else:
        blade = f"M {x} {y+10} L {x+5} {y+18}"

    tx = x - 34 if "1" in label else x + 16

    return f"""
    {sld_wire(x, y, x, y+10, ext_color)}
    <path d="{blade}" stroke="{color}" stroke-width="4"
          fill="none" stroke-linecap="round"/>
    {sld_wire(x, y+30, x, y+40, bus_color)}
    <text x="{tx}" y="{y+22}" font-size="11" font-weight="600"
          fill="{SLD['sub']}" font-family="sans-serif">{html.escape(label)}</text>
    <text x="{tx}" y="{y+35}" font-size="9" font-weight="700"
          fill="{color}" font-family="sans-serif">{status}</text>
    """


def draw_gi(x, name, cb_status, fault=False, bus_live=False, out_live=False):
    color = SWITCH_COLOR.get(cb_status, "#64748b")
    bus_color = SLD["on"] if bus_live else SLD["off"]
    out_color = SLD["on"] if out_live else SLD["off"]
    alert = (
        f'<text x="{x}" y="138" font-size="11" fill="{SLD["fault"]}" '
        f'text-anchor="middle" font-weight="bold" class="blinking">TRIP / UV</text>'
        if fault else ""
    )

    return f"""
    {sld_wire(x-40, 50, x+40, 50, bus_color, 5)}
    <text x="{x}" y="38" font-size="13" fill="{SLD['text']}"
          font-weight="bold" text-anchor="middle">{html.escape(name)}</text>
    <text x="{x+46}" y="54" font-size="10" fill="{SLD['sub']}">20kV</text>

    {sld_wire(x, 50, x, 80, bus_color)}

    <rect x="{x-11}" y="80" width="22" height="22" rx="3"
          fill="{color}" stroke="{SLD['box_border']}" stroke-width="1"/>
    <text x="{x+17}" y="95" font-size="11" font-weight="600"
          fill="{SLD['sub']}">CB</text>
    <text x="{x}" y="116" font-size="10" font-weight="700" fill="{color}"
          text-anchor="middle">{cb_status}</text>

    {sld_wire(x, 102, x, 150, out_color)}
    {alert}
    """


def draw_gd(
    x, name, lbs1_status, lbs2_status, arus,
    ext1_color, ext2_color, bus_live=False,
    is_nop=False, hfd=False, uv=False, ov=False,
):
    bus_color = SLD["on"] if bus_live else SLD["off"]

    nop_text = (
        f'<text x="{x+28}" y="223" font-size="10" fill="#f59e0b" '
        f'font-weight="bold">NOP</text>'
        if is_nop else ""
    )

    if hfd:
        status_text = f'<text x="{x}" y="415" font-size="12" fill="{SLD["fault"]}" text-anchor="middle" font-weight="bold" class="blinking">TRIP / HFD</text>'
    elif uv:
        status_text = f'<text x="{x}" y="415" font-size="11" fill="#f59e0b" text-anchor="middle" font-weight="bold" class="blinking">UV</text>'
    elif ov:
        status_text = f'<text x="{x}" y="415" font-size="11" fill="#f59e0b" text-anchor="middle" font-weight="bold" class="blinking">OV</text>'
    else:
        status_text = f'<text x="{x}" y="415" font-size="11" font-weight="600" fill="#10b981" text-anchor="middle">AMAN</text>'

    return f"""
    {sld_wire(x-20, 150, x-20, 170, ext1_color)}
    {sld_wire(x+20, 150, x+20, 170, ext2_color)}

    {draw_lbs(x-20, 170, lbs1_status, "LBS1", ext1_color, bus_color)}
    {draw_lbs(x+20, 170, lbs2_status, "LBS2", ext2_color, bus_color)}
    {nop_text}

    {sld_wire(x-20, 210, x-20, 230, bus_color)}
    {sld_wire(x+20, 210, x+20, 230, bus_color)}

    {sld_wire(x-40, 230, x+40, 230, bus_color, 5)}
    <text x="{x-46}" y="235" font-size="13" fill="{SLD['text']}"
          font-weight="bold" text-anchor="end">{html.escape(name)}</text>

    {sld_wire(x, 230, x, 250, bus_color)}
    <rect x="{x-8}" y="250" width="16" height="16" rx="2"
          fill="{bus_color}" stroke="{SLD['box_border']}" stroke-width="1"/>
    <text x="{x+13}" y="262" font-size="10" fill="{SLD['sub']}">CBOG</text>

    {sld_wire(x, 266, x, 295, bus_color, 2)}

    <circle cx="{x}" cy="305" r="10" fill="none"
            stroke="{bus_color}" stroke-width="2"/>
    <circle cx="{x}" cy="317" r="10" fill="none"
            stroke="{bus_color}" stroke-width="2"/>

    {sld_wire(x, 327, x, 340, bus_color, 2)}
    <line x1="{x-6}" y1="340" x2="{x+6}" y2="340"
          stroke="{SLD['sub']}" stroke-width="1"/>
    <line x1="{x-4}" y1="344" x2="{x+4}" y2="344"
          stroke="{SLD['sub']}" stroke-width="1"/>
    <line x1="{x-2}" y1="348" x2="{x+2}" y2="348"
          stroke="{SLD['sub']}" stroke-width="1"/>

    <rect x="{x-27}" y="365" width="54" height="22"
          fill="{SLD['box']}" stroke="{SLD['box_border']}" rx="4"/>
    <text x="{x}" y="381" font-size="13" fill="{SLD['readout']}"
          text-anchor="middle" font-family="monospace"
          font-weight="bold">{arus}A</text>

    {status_text}
    """


def draw_fault_icon(x, y, is_active):
    if not is_active:
        return ""
    return (
        f'<polygon points="{x},{y-18} {x-10},{y+3} {x-3},{y+3} '
        f'{x-6},{y+18} {x+10},{y-3} {x+3},{y-3}" '
        f'fill="#facc15" stroke="#ca8a04" stroke-width="1" class="blinking" />'
    )


def compute_energization(gi1, gi2, gds):
    """Tentukan segmen/busbar mana yang bertegangan dari posisi switch.

    Sumber = GI yang online dan tidak UV. Tegangan menjalar lewat switch
    yang CLOSE di kedua sisi, sehingga NOP GD03-LBS2 yang OPEN memutus
    aliran dari GI SATU, dan GI DUA menyuplai dari sisi sebaliknya.
    """
    src1 = bool(gi1.get("online")) and not gi1.get("uv", False)
    src2 = bool(gi2.get("online")) and not gi2.get("uv", False)

    # Switch di ujung kiri / kanan tiap segmen (6 segmen)
    left_sw = [bool(gi1.get("cb_closed"))] + [bool(g.get("lbs2_closed")) for g in gds]
    right_sw = [bool(g.get("lbs1_closed")) for g in gds] + [bool(gi2.get("cb_closed"))]

    bus = [src1, False, False, False, False, False, src2]
    seg = [False] * 6

    for _ in range(8):
        changed = False
        for k in range(6):
            live = (left_sw[k] and bus[k]) or (right_sw[k] and bus[k + 1])
            if live != seg[k]:
                seg[k], changed = live, True
        for n in range(1, 6):
            live = (right_sw[n - 1] and seg[n - 1]) or (left_sw[n] and seg[n])
            if live != bus[n]:
                bus[n], changed = live, True
        if not changed:
            break

    return seg, bus


def build_sld(rtus, controller):
    ir = controller["ir"]

    phase = safe_int(ir[IR_PHASE])
    target = safe_int(ir[IR_TARGET])

    offline_gi = {
        "online": False, "cb": "OFFLINE", "cb_closed": False,
        "trip": False, "uv": False, "ov": False,
    }

    def gi_of(name):
        info = rtus[name]
        if not info["online"]:
            return dict(offline_gi)
        return {**gi_status(info), "online": True}

    def gd_of(name):
        info = rtus[name]
        return gd_status(info) if info["online"] else {}

    gi1 = gi_of("GI SATU")
    gi2 = gi_of("GI DUA")
    gds = [gd_of(f"GD0{i}") for i in range(1, 6)]

    seg_live, bus_live = compute_energization(gi1, gi2, gds)

    xs = [100, 230, 370, 510, 650, 790, 920]

    seg_fault = [
        target == k + 1 and phase in (4, 5, 6, 8, 9) for k in range(6)
    ]

    seg_color = [
        SLD["fault"] if seg_fault[k]
        else SLD["on"] if seg_live[k]
        else SLD["off"]
        for k in range(6)
    ]

    lines = []
    for k in range(6):
        # Feeder menyambung dari kaki kanan GD (x+20) ke kaki kiri GD berikut (x-20);
        # untuk GI, feeder menyambung ke garis vertikal di x.
        x1 = xs[k] + (0 if k == 0 else 20)
        x2 = xs[k + 1] - (0 if k == 5 else 20)

        dash = "" if seg_live[k] or seg_fault[k] else ' stroke-dasharray="6,5"'
        lines.append(
            f'<line x1="{x1}" y1="150" x2="{x2}" y2="150" '
            f'stroke="{seg_color[k]}" stroke-width="3" '
            f'stroke-linecap="round"{dash}/>'
        )
        if seg_live[k] and not seg_fault[k]:
            # Titik putih bergerak di atas garis solid = indikator tegangan mengalir
            lines.append(
                f'<line class="flow" x1="{x1}" y1="150" x2="{x2}" y2="150" '
                f'stroke="#ffffff" stroke-opacity="0.65" stroke-width="1.5" '
                f'stroke-linecap="round"/>'
            )
        lines.append(draw_fault_icon((x1 + x2) // 2, 150, seg_fault[k]))

    gd_blocks = []
    for i, g in enumerate(gds):
        n = i + 1
        gd_blocks.append(
            draw_gd(
                xs[n], f"GD0{n}",
                g.get("lbs1", "OFFLINE"),
                g.get("lbs2", "OFFLINE"),
                g.get("current", 0),
                ext1_color=seg_color[n - 1],
                ext2_color=seg_color[n],
                bus_live=bus_live[n],
                is_nop=(n == 3),
                hfd=g.get("hfd", False),
                uv=g.get("uv", False),
                ov=g.get("ov", False),
            )
        )

    legend_items = [
        (SLD["on"], "Bertegangan"),
        (SLD["off"], "Padam"),
        (SLD["fault"], "Gangguan"),
        (SWITCH_COLOR["CLOSE"], "CLOSE"),
        (SWITCH_COLOR["OPEN"], "OPEN"),
        (SWITCH_COLOR["TRANSIT"], "TRANSIT"),
    ]
    legend = ""
    lx = 24
    for color, text in legend_items:
        legend += (
            f'<rect x="{lx}" y="428" width="12" height="12" rx="3" fill="{color}"/>'
            f'<text x="{lx+18}" y="438" font-size="11" fill="{SLD["sub"]}">{text}</text>'
        )
        lx += 30 + len(text) * 7

    svg = f"""
    <svg width="100%" height="450" font-family="'Segoe UI', Arial, sans-serif"
         viewBox="0 0 1050 450"
         xmlns="http://www.w3.org/2000/svg"
         class="sld"
         style="background:{SLD['bg']};border-radius:12px;border:1px solid {SLD['border']};">

        {''.join(lines)}

        {draw_gi(100, "GI SATU", gi1["cb"],
                 fault=(gi1["trip"] or gi1["uv"]),
                 bus_live=bus_live[0],
                 out_live=seg_live[0] and gi1["cb_closed"])}

        {''.join(gd_blocks)}

        {draw_gi(920, "GI DUA", gi2["cb"],
                 fault=(gi2["trip"] or gi2["uv"]),
                 bus_live=bus_live[6],
                 out_live=seg_live[5] and gi2["cb_closed"])}

        {legend}
        <text x="1026" y="438" fill="{SLD['sub']}" font-size="10"
              text-anchor="end">
              Controller {HOST}:{CONTROLLER_PORT}
        </text>
    </svg>
    """

    # st.markdown menganggap baris berindentasi sebagai code block dan baris kosong
    # sebagai akhir blok HTML, jadi ratakan SVG menjadi satu baris.
    return " ".join(line.strip() for line in svg.splitlines() if line.strip())


# ============================================================
# SOE
# ============================================================

# Gaya tiap tahap di tabel SOE: (label, jenis pill)
SOE_STAGE = {
    "lokalisasi": ("LOKALISASI", "bad"),
    "isolasi": ("ISOLASI", "warn"),
    "restorasi": ("RESTORASI", "info"),
    "selesai": ("SELESAI", "ok"),
    "selesai sebagian": ("SEBAGIAN", "warn"),
    "kelayakan": ("KELAYAKAN", "warn"),
    "proteksi": ("PROTEKSI", "warn"),
    "timeout": ("TIMEOUT", "bad"),
    "kesalahan": ("KESALAHAN", "bad"),
    "test": ("TEST", "mute"),
}

# Kata kunci pada keterangan yang menandakan langkah gagal
SOE_FAIL_WORDS = ("gagal", "ditolak", "lock-out", "kontradiktif", "hilang")


def read_soe(limit=20):
    """Baca soe.csv. Hasil: (daftar event terbaru dulu, total event)."""
    if not SOE_FILE.exists():
        return [], 0

    try:
        with open(SOE_FILE, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [
                {k: (v or "").strip() for k, v in row.items() if k}
                for row in reader
                if any((v or "").strip() for v in row.values())
            ]
    except (OSError, csv.Error):
        return [], 0

    return rows[::-1][:limit], len(rows)


def build_soe_table(rows):
    body = []
    for row in rows:
        stage_key = row.get("tahap", "").lower()
        label, kind = SOE_STAGE.get(stage_key, (stage_key.upper() or "-", "mute"))
        desc = row.get("keterangan", "")

        failed = any(word in desc.lower() for word in SOE_FAIL_WORDS)
        if failed and kind not in ("bad",):
            kind = "bad"

        stamp = row.get("waktu", "")
        date, _, clock = stamp.partition(" ")
        if not clock:
            date, clock = "", stamp

        try:
            duration = f"{float(row.get('detik', '')):.2f} s"
        except ValueError:
            duration = "—"

        body.append(
            "<tr>"
            f'<td class="mono"><span class="soe-time">{html.escape(clock)}</span>'
            f'<span class="soe-date">{html.escape(date)}</span></td>'
            f'<td><span class="pill {kind}">{html.escape(label)}</span></td>'
            f'<td class="soe-desc">{html.escape(desc)}</td>'
            f'<td class="mono num">{duration}</td>'
            "</tr>"
        )

    return (
        '<div class="tbl-wrap"><table class="tbl soe"><thead><tr>'
        "<th>Waktu</th><th>Tahap</th><th>Keterangan</th>"
        '<th class="num">Durasi</th>'
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>"
    )


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

st.caption(
    f"Mode komunikasi HMI: {'Y — melalui Saitel HUe (CHFLISR)' if FLISR_MODE == 'Y' else 'N — langsung ke simulator RTU'} · "
    + ("Reset HUe aktif (pemetaan sudah diaktifkan)." if FLISR_MODE == "Y" and HUE_RESET_MAP_ENABLED else
       "Reset HUe terkunci sampai EBC reset-mapped dikirim dan diverifikasi." if FLISR_MODE == "Y" else
       "Status RTU menggunakan FC01; selector merupakan kontrol simulasi.")
)

controller, controller_err = read_controller()
if controller_err:
    st.error(f"Controller: {controller_err}")
    st.stop()

rtus = read_rtus()
lr_states = {
    item["key"]: selector_state(
        rtus.get(item["rtu"]), item["local_cs"], item["remote_cs"]
    )
    for item in LR_SWITCHES
}
lr_remote_count = sum(state == "REMOTE" for state in lr_states.values())
lr_all_remote = lr_remote_count == len(LR_SWITCHES)
behavior, behavior_err = read_behavior()


# ============================================================
# SIDEBAR STATUS HELPERS
# ============================================================

def sidebar_status_row(label, value, detail=""):
    """Compact live-status item for the sidebar monitoring menu."""
    normalized = str(value).upper()
    if any(word in normalized for word in ("ACTIVE", "TRIP", "INVALID")):
        color = "#ef4444"
    elif any(word in normalized for word in ("OFFLINE", "NO FEEDBACK")):
        color = "#94a3b8"
    elif any(word in normalized for word in ("LOCAL", "OPEN", "TRANSIT", "UNKNOWN")):
        color = "#f59e0b"
    elif any(word in normalized for word in ("REMOTE", "CLOSE", "CLEAR", "NORMAL", "NO ALARM", "OK")):
        color = "#10b981"
    else:
        color = "#60a5fa"

    detail_html = (
        f'<div style="font-size:10px;color:var(--muted);margin-top:2px">{html.escape(str(detail))}</div>'
        if detail else ""
    )
    html_block = (
        f'<div style="display:flex;align-items:flex-start;gap:8px;padding:7px 8px;margin:4px 0;'
        f'border:1px solid var(--border);border-radius:8px;background:var(--card);">'
        f'<span style="width:8px;height:8px;min-width:8px;border-radius:50%;background:{color};margin-top:4px;"></span>'
        f'<div style="min-width:0;flex:1;line-height:1.25;">'
        f'<div style="font-size:11px;font-weight:750;color:var(--text);">{html.escape(str(label))}</div>'
        f'<div style="font-size:11px;color:var(--text);margin-top:2px;overflow-wrap:anywhere;">{html.escape(str(value))}</div>'
        f'{detail_html}</div></div>'
    )
    st.markdown(html_block, unsafe_allow_html=True)


def state_alarm(active):
    return "ACTIVE" if bool(active) else "CLEAR"


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
    if lr_all_remote:
        st.success(f"Selector REMOTE: {lr_remote_count}/{len(LR_SWITCHES)} — interlock L/R terpenuhi.")
    else:
        st.warning(
            f"Selector REMOTE: {lr_remote_count}/{len(LR_SWITCHES)}. "
            "FLISR tidak akan SIAGA sampai semua CB/LBS REMOTE."
        )

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "ENABLE",
            width="stretch",
            disabled=(shg_enabled or not lr_all_remote),
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

    st.markdown("## 🚨 ALARM SUMMARY")
    _sidebar_hfd = 0
    _sidebar_uv = 0
    _sidebar_ov = 0
    _sidebar_offline = 0
    for _node_name, _node_info in rtus.items():
        if not _node_info.get("online"):
            _sidebar_offline += 1
            continue
        if _node_name.startswith("GI"):
            _alarm = gi_status(_node_info)
            _sidebar_uv += int(_alarm["uv"])
            _sidebar_ov += int(_alarm["ov"])
        else:
            _alarm = gd_status(_node_info)
            _bits = _node_info.get("cs", [])
            _sidebar_hfd += int(bool(_bits[0])) if len(_bits) > 0 else 0
            _sidebar_hfd += int(bool(_bits[5])) if len(_bits) > 5 else 0
            _sidebar_uv += int(_alarm["uv"])
            _sidebar_ov += int(_alarm["ov"])
    st.caption(f"HFD aktif: {_sidebar_hfd} titik · UV: {_sidebar_uv} gardu · OV: {_sidebar_ov} gardu")
    if _sidebar_offline:
        st.warning(f"RTU offline: {_sidebar_offline}/7")
    elif _sidebar_hfd or _sidebar_uv or _sidebar_ov:
        st.error("Ada alarm aktif. Buka panel status utama untuk detail.")
    else:
        st.success("Tidak ada alarm HFD/UV/OV aktif.")

    st.divider()

    st.markdown("## 🧪 FAULT SIMULATOR")
    st.markdown(
        """
        <div class="side-note">
        Tombol fault menulis ke <b>System Behavior :503</b>.
        Controller tidak membaca layanan Testbench port 503.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if behavior_err:
        st.warning("Testbench port 503 belum terhubung.")

    _fault_notice = st.session_state.pop("fault_case_notice", None)
    if _fault_notice:
        if _fault_notice[0]:
            st.success(_fault_notice[1])
        else:
            st.warning(_fault_notice[1])

    st.caption("Setiap kasus sekarang diterapkan sebagai satu transaksi: controller ditahan sementara, latch lama di-clear, pola HFD ditulis dan diverifikasi, lalu controller diaktifkan kembali.")
    fault_cols = st.columns(2)

    for i, seg_name in enumerate(SEGMENT_NAMES):
        with fault_cols[i % 2]:
            if st.button(
                f"💥 K{i+1}",
                width="stretch",
                key=f"fault_{i+1}",
                disabled=(behavior_err is not None or not shg_enabled),
            ):
                ok, msg = submit_fault_case(i + 1)
                st.session_state["fault_case_notice"] = (ok, msg)
                st.rerun()

    st.caption("Source fault: CB GI yang fault OPEN → NOP GD03-LBS2 CLOSE → suplai berpindah ke GI sehat.")

    s1, s2 = st.columns(2)

    with s1:
        if st.button(
            "⚡ GI SATU FAULT",
            width="stretch",
            disabled=(behavior_err is not None or not shg_enabled),
        ):
            ok, msg = submit_fault_case(7)
            st.session_state["fault_case_notice"] = (ok, msg)
            st.rerun()

    with s2:
        if st.button(
            "⚡ GI DUA FAULT",
            width="stretch",
            disabled=(behavior_err is not None or not shg_enabled),
        ):
            ok, msg = submit_fault_case(8)
            st.session_state["fault_case_notice"] = (ok, msg)
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
            status, err = mb_read(CONTROLLER_PORT, "di", 0, CONTROLLER_DI_COUNT)
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
# ALERT BANNER
# ============================================================

def target_label(t):
    if 1 <= t <= 6:
        return f"K{t} · {SEGMENT_NAMES[t - 1]}"
    if t == 7:
        return "Sumber GI SATU"
    if t == 8:
        return "Sumber GI DUA"
    return ""


def build_alert(phase, target, padam, lockout):
    where = target_label(target)
    suffix = f" — {where}" if where else ""

    if lockout or phase == 9:
        return (
            "crit", "🔒",
            "LOCK-OUT — menunggu reset operator",
            "Tekan RESET LOCK-OUT di sidebar untuk melanjutkan.",
        )
    if phase == 4:
        return ("crit", "🚨", f"GANGGUAN TERDETEKSI{suffix}", PHASE_DESC[4])
    if phase == 5:
        return ("crit", "⚡", f"ISOLASI SEGMEN RUSAK{suffix}", PHASE_DESC[5])
    if phase == 6:
        return ("warn", "🔧", f"RESTORASI SUPLAI{suffix}", PHASE_DESC[6])
    if phase == 8:
        return (
            "warn", "⚠️",
            f"PENANGANAN SEBAGIAN{suffix}",
            f"{PHASE_DESC[8]} · {padam} gardu masih padam",
        )
    return None


alert = build_alert(phase, target, padam, lockout)
if alert:
    kind, icon, title, sub = alert
    st.markdown(
        f"""
        <div class="alert {kind}">
            <div class="alert-icon">{icon}</div>
            <div>
                <div class="alert-title">{html.escape(title)}</div>
                <div class="alert-sub">{html.escape(sub)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
# PROGRES FLISR
# ============================================================

FLISR_STEPS = [
    (3, "Siaga"),
    (4, "Lokalisasi"),
    (5, "Isolasi"),
    (6, "Restorasi"),
    (7, "Selesai"),
]


def step_state(step_phase, current):
    if current == 7:
        return "done"
    if current == 8:
        return "done" if step_phase < 7 else "partial"
    if 3 <= current <= 6:
        if step_phase < current:
            return "done"
        return "active" if step_phase == current else "todo"
    return "todo"  # menunggu RTU / disable / belum siaga / lock-out


def build_stepper(current):
    parts = []
    for i, (step_phase, label) in enumerate(FLISR_STEPS):
        state = step_state(step_phase, current)
        mark = {"done": "✓", "partial": "!"}.get(state, str(i + 1))
        if step_phase == 7 and state == "partial":
            label = "Sebagian"
        parts.append(
            f'<div class="step {state}"><div class="step-dot">{mark}</div>'
            f'<div class="step-label">{label}</div></div>'
        )
        if i < len(FLISR_STEPS) - 1:
            nxt = step_state(FLISR_STEPS[i + 1][0], current)
            line = "done" if nxt in ("done", "active", "partial") else ""
            parts.append(f'<div class="step-line {line}"></div>')
    return '<div class="stepper">' + "".join(parts) + "</div>"


st.markdown('<div class="section">🚦 PROGRES FLISR</div>', unsafe_allow_html=True)
st.markdown(build_stepper(phase), unsafe_allow_html=True)
st.markdown(
    f'<div class="stepper-note">Fase saat ini: <b>{html.escape(PHASE_NAME.get(phase, f"FASE {phase}"))}</b>'
    f' — {html.escape(PHASE_DESC.get(phase, ""))}</div>',
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

st.markdown(build_sld(rtus, controller), unsafe_allow_html=True)


# ============================================================
# EQUIPMENT STATUS & CONTROL — TWO VIEWS
# ============================================================

st.markdown('<div class="section">🎛️ Equipment Status & Control</div>', unsafe_allow_html=True)
st.caption(
    "Pilih CB & LBS Status untuk melihat posisi switch, mengatur selector Local/Remote, "
    "dan mengirim perintah OPEN/CLOSE melalui HMI. Pilih UV & HFD Status untuk memantau "
    "alarm proteksi serta melakukan reset HFD/trip yang tersedia."
)

status_panel = st.segmented_control(
    "Pilih panel",
    options=["CB & LBS Status", "UV & HFD Status"],
    default="CB & LBS Status",
    key="equipment_status_control_view",
    label_visibility="collapsed",
    width="stretch",
)

if status_panel == "CB & LBS Status":
    switch_rows = []
    for item in LR_SWITCHES:
        info = rtus.get(item["rtu"], {})
        lr = lr_states[item["key"]]
        if not info.get("online"):
            position = "OFFLINE"
            trip = False
        elif item["rtu"].startswith("GI"):
            _sw = gi_status(info)
            position = _sw["cb"]
            trip = bool(_sw["trip"])
        else:
            _sw = gd_status(info)
            position = _sw["lbs1"] if item["label"].endswith("LBS1") else _sw["lbs2"]
            trip = False
        switch_rows.append({"item": item, "info": info, "lr": lr, "position": position, "trip": trip})

    _closed_count = sum(r["position"] == "CLOSE" for r in switch_rows)
    _open_count = sum(r["position"] == "OPEN" for r in switch_rows)
    _switch_uncertain = sum(r["position"] not in ("OPEN", "CLOSE") for r in switch_rows)
    _local_count = sum(r["lr"] == "LOCAL" for r in switch_rows)

    _mc = st.columns(4)
    _mc[0].metric("SWITCH CLOSE", _closed_count)
    _mc[1].metric("SWITCH OPEN", _open_count)
    _mc[2].metric("LOCAL SELECTOR", _local_count)
    _mc[3].metric("INVALID / OFFLINE / TRANSIT", _switch_uncertain)

    _manual_shg_enabled = bool(controller["coils"][CO_SHG_ENABLE]) if len(controller.get("coils", [])) > CO_SHG_ENABLE else False
    if _manual_shg_enabled:
        st.warning("SHG sedang ENABLED. Perintah manual OPEN/CLOSE dinonaktifkan untuk mencegah konflik dengan urutan otomatis FLISR. Disable SHG dahulu untuk switching manual.")
    else:
        st.info("Manual switching hanya diizinkan bila RTU online, selector REMOTE, dan posisi switch valid. Tombol Set LOCAL/REMOTE mengubah HR selector pada simulator (bukan aktuator selector fisik).")

    _head = st.columns([1.65, 0.8, 0.85, 0.8, 0.8, 0.65, 0.65])
    for _col, _label in zip(_head, ["Equipment", "Position", "Feedback L/R", "Set LOCAL", "Set REMOTE", "OPEN", "CLOSE"]):
        _col.markdown(f"**{_label}**")

    for _row_data in switch_rows:
        item = _row_data["item"]
        info = _row_data["info"]
        state = _row_data["lr"]
        position = _row_data["position"]
        trip = _row_data["trip"]
        is_online = bool(info.get("online"))
        is_gi = item["rtu"].startswith("GI")
        _bay = 0 if (is_gi or item["label"].endswith("LBS1")) else 1

        _row = st.columns([1.65, 0.8, 0.85, 0.8, 0.8, 0.65, 0.65])
        with _row[0]:
            st.markdown(f"**{item['label']}**")
            _sel_host, _sel_tcp_port = resolve_modbus_endpoint(item["port"], simulator=True)
            st.caption(f"RTU {_sel_host}:{_sel_tcp_port} · selector HR{item['hr']}")
        with _row[1]:
            _position_label = f"{position} · TRIP" if (is_gi and trip) else position
            if position == "CLOSE":
                st.markdown(f"🟢 **{_position_label}**")
            elif position == "OPEN":
                st.markdown(f"🔴 **{_position_label}**")
            elif position == "TRANSIT":
                st.markdown(f"🟠 **{_position_label}**")
            elif position == "OFFLINE":
                st.markdown(f"⚫ **{_position_label}**")
            else:
                st.markdown(f"⚠️ **{html.escape(_position_label)}**")
        with _row[2]:
            if state == "REMOTE":
                st.markdown("🟢 **REMOTE**")
            elif state == "LOCAL":
                st.markdown("🟠 **LOCAL**")
            elif state == "OFFLINE":
                st.markdown("🔴 **OFFLINE**")
            else:
                st.markdown(f"⚠️ **{html.escape(state)}**")
        with _row[3]:
            if st.button("LOCAL", key=f"panel_local_{item['key']}", width="stretch", disabled=(not is_online or state == "LOCAL")):
                _ok, _msg = mb_write(item["port"], "hr", item["hr"], 0, simulator=True)
                if not _ok:
                    st.error(f"{item['label']}: {_msg}")
                else:
                    time.sleep(0.08)
                    st.rerun()
        with _row[4]:
            if st.button("REMOTE", key=f"panel_remote_{item['key']}", width="stretch", disabled=(not is_online or state == "REMOTE")):
                _ok, _msg = mb_write(item["port"], "hr", item["hr"], 1, simulator=True)
                if not _ok:
                    st.error(f"{item['label']}: {_msg}")
                else:
                    time.sleep(0.08)
                    st.rerun()

        _remote_manual_ok = is_online and state == "REMOTE" and not _manual_shg_enabled and position in ("OPEN", "CLOSE")
        with _row[5]:
            if st.button("OPEN", key=f"panel_open_{item['key']}", width="stretch", disabled=(not _remote_manual_ok or position == "OPEN")):
                _ok, _msg = send_manual_switch(item["port"], _bay, closed=False)
                if not _ok:
                    st.error(f"Gagal OPEN {item['label']}: {_msg}")
                else:
                    st.success(f"{item['label']}: {_msg}")
                    st.rerun()
        with _row[6]:
            if st.button("CLOSE", key=f"panel_close_{item['key']}", width="stretch", disabled=(not _remote_manual_ok or position == "CLOSE" or trip)):
                _ok, _msg = send_manual_switch(item["port"], _bay, closed=True)
                if not _ok:
                    st.error(f"Gagal CLOSE {item['label']}: {_msg}")
                else:
                    st.success(f"{item['label']}: {_msg}")
                    st.rerun()
        st.divider()

    if not lr_all_remote:
        st.warning(
            f"INTERLOCK FLISR: hanya {lr_remote_count}/{len(LR_SWITCHES)} selector REMOTE. "
            "FLISR tidak boleh SIAGA sampai seluruh CB/LBS berstatus REMOTE."
        )
    else:
        st.success("Seluruh 12 selector REMOTE — syarat L/R untuk kesiagaan FLISR terpenuhi jika syarat lain juga normal.")

else:
    # Protection/alarm view: status is read from RTU feedback. HFD/trip reset
    # are commands; UV/OV clear when the underlying telemetry/fault condition clears.
    _hfd_count = 0
    _uv_count = 0
    _ov_count = 0
    _trip_count = 0
    _alarm_rows = []
    for _name, _info in rtus.items():
        if not _info.get("online"):
            _alarm_rows.append({"name": _name, "online": False})
            continue
        if _name.startswith("GI"):
            _g = gi_status(_info)
            _row = {"name": _name, "online": True, "hfd1": None, "hfd2": None,
                    "uv": _g["uv"], "ov": _g["ov"], "trip": _g["trip"],
                    "voltage": _g["voltage"], "current": _g["current"]}
            _uv_count += int(_g["uv"])
            _ov_count += int(_g["ov"])
            _trip_count += int(_g["trip"])
        else:
            _g = gd_status(_info)
            _bits = _info.get("cs", [])
            _h1 = bool(_bits[0]) if len(_bits) > 0 else False
            _h2 = bool(_bits[5]) if len(_bits) > 5 else False
            _row = {"name": _name, "online": True, "hfd1": _h1, "hfd2": _h2,
                    "uv": _g["uv"], "ov": _g["ov"], "trip": None,
                    "voltage": _g["voltage"], "current": _g["current"]}
            _hfd_count += int(_h1) + int(_h2)
            _uv_count += int(_g["uv"])
            _ov_count += int(_g["ov"])
        _alarm_rows.append(_row)

    _am = st.columns(4)
    _am[0].metric("HFD ACTIVE", f"{_hfd_count} titik")
    _am[1].metric("UNDER-VOLTAGE", f"{_uv_count} gardu")
    _am[2].metric("OVER-VOLTAGE", f"{_ov_count} gardu")
    _am[3].metric("GI TRIP", f"{_trip_count} sumber")

    st.caption("HFD/Trip dapat di-reset dari HMI. Pada Mode Y, tombol reset aktif hanya setelah EBC reset-mapped dikirim ke HUe dan FLISR_HUE_RESET_MAP diaktifkan saat startup. UV/OV mengikuti telemetry simulator dan tidak di-reset paksa.")
    _ah = st.columns([1.1, 0.65, 0.65, 0.65, 0.65, 0.65, 0.85, 0.9, 0.8])
    for _col, _label in zip(_ah, ["Equipment", "HFD1", "HFD2", "UV", "OV", "GI Trip", "Voltage (V)", "Current (A)", "Reset"]):
        _col.markdown(f"**{_label}**")

    for _row in _alarm_rows:
        _name = _row["name"]
        _info = rtus.get(_name, {})
        _online = bool(_row.get("online"))
        _cols = st.columns([1.1, 0.65, 0.65, 0.65, 0.65, 0.65, 0.85, 0.9, 0.8])
        _cols[0].markdown(f"**{_name}**")
        if not _online:
            for _idx in range(1, 8):
                _cols[_idx].markdown("—")
            _cols[8].markdown("🔴 OFFLINE")
            st.divider()
            continue

        if _name.startswith("GI"):
            _cols[1].markdown("—")
            _cols[2].markdown("—")
        else:
            _cols[1].markdown("🔴 ACTIVE" if _row["hfd1"] else "🟢 CLEAR")
            _cols[2].markdown("🔴 ACTIVE" if _row["hfd2"] else "🟢 CLEAR")
        _cols[3].markdown("🔴 ACTIVE" if _row["uv"] else "🟢 CLEAR")
        _cols[4].markdown("🔴 ACTIVE" if _row["ov"] else "🟢 CLEAR")
        _cols[5].markdown(("🔴 TRIP" if _row["trip"] else "🟢 CLEAR") if _name.startswith("GI") else "—")
        _cols[6].markdown(f"{_row['voltage']:,}")
        _cols[7].markdown(f"{_row['current']:,}")

        if _name.startswith("GI"):
            if _cols[8].button("RESET TRIP", key=f"reset_trip_{_name}", width="stretch",
                               disabled=(not _row["trip"] or (FLISR_MODE == "Y" and not HUE_RESET_MAP_ENABLED))):
                _ok, _msg = send_protection_reset(RTU_PORTS[_name])
                if not _ok:
                    st.error(f"Reset trip {_name} gagal: {_msg}")
                else:
                    st.success(f"Reset trip {_name}: {_msg}")
                    st.rerun()
        else:
            _hfd_any = bool(_row["hfd1"] or _row["hfd2"])
            if _cols[8].button("RESET HFD", key=f"reset_hfd_{_name}", width="stretch",
                               disabled=(not _hfd_any or (FLISR_MODE == "Y" and not HUE_RESET_MAP_ENABLED))):
                _ok, _msg = send_protection_reset(RTU_PORTS[_name])
                if not _ok:
                    st.error(f"Reset HFD {_name} gagal: {_msg}")
                else:
                    st.success(f"Reset HFD {_name}: {_msg}")
                    st.rerun()
        st.divider()

    if _hfd_count or _uv_count or _ov_count or _trip_count:
        st.warning("Satu atau lebih indikator proteksi sedang aktif. Periksa penyebab gangguan sebelum melakukan reset.")
    else:
        st.success("Semua indikator HFD, UV, OV, dan GI trip sedang CLEAR.")


# ============================================================
# NODE HEALTH
# ============================================================

st.markdown('<div class="section">🧩 Node Health</div>', unsafe_allow_html=True)

node_cols = st.columns(7)

for idx, (name, port) in enumerate(RTU_PORTS.items()):
    info = rtus[name]
    online = info["online"]
    _node_host, _node_tcp_port = resolve_modbus_endpoint(port)

    with node_cols[idx]:
        state = "ONLINE" if online else "OFFLINE"
        badge_kind = "ok" if online else "bad"

        st.markdown(
            f"""
            <div class="node-card">
                <div class="node-name">
                    {"🟢" if online else "🔴"} {html.escape(name)}
                </div>
                <div class="small-muted">{_node_host}:{_node_tcp_port}</div>
                <div class="node-badge {badge_kind}">{state}</div>
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
                "Selector L/R": "OFFLINE",
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
                "Selector L/R": f"CB {selector_state(info, 3, 4)}",
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
                "Selector L/R": f"LBS1 {selector_state(info, 3, 4)} / LBS2 {selector_state(info, 8, 9)}",
                "Tegangan (V)": s["voltage"],
                "Arus (A)": s["current"],
            }
        )

_tbl_head = "".join(f"<th>{html.escape(k)}</th>" for k in telemetry_rows[0])
_tbl_body = "".join(
    "<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row.values()) + "</tr>"
    for row in telemetry_rows
)
st.markdown(
    f'<table class="tbl"><thead><tr>{_tbl_head}</tr></thead><tbody>{_tbl_body}</tbody></table>',
    unsafe_allow_html=True,
)


# ============================================================
# SOE
# ============================================================

soe_rows, soe_total = read_soe(20)

st.markdown(
    '<div class="section">🧾 Sequence of Events'
    f'<span class="section-note">{soe_total} event'
    f'{" · menampilkan 20 terbaru" if soe_total > 20 else ""}</span></div>',
    unsafe_allow_html=True,
)

if soe_rows:
    st.markdown(build_soe_table(soe_rows), unsafe_allow_html=True)
else:
    st.markdown(
        '<div class="empty-state">Belum ada event. Event akan muncul di sini '
        "saat controller mendeteksi dan menangani gangguan.</div>",
        unsafe_allow_html=True,
    )


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
