import os
"""Peta jaringan dan kontrak alamat Modbus untuk simulasi FLISR.

One-laptop physical-Ethernet architecture:
- Laptop Ethernet aliases: 192.168.250.2..192.168.250.9/24
- Controller status server: 192.168.250.2:502
- Testbench/System Behavior: 192.168.250.2:503
- Web HMI: http://192.168.250.2:8501
- Seven independent GI/GD RTU simulators each listen on their own IP at TCP/502.
- Mode N: controller.py is a Modbus TCP client directly to .3..9.
- Mode Y: controller_rtu.py is a Modbus TCP client to HUe CHFLISR at 192.168.250.1:502,
  using server Unit IDs 1..7. The EBC Mdbm master uses its own configured downstream
  Unit IDs (1,2,2,3,4,2,3 in NODE order).
- Physical Saitel HUe MNT interface: 192.168.250.1/24 (verify in the live RTU config).
- PLC1/PLC2 interface addresses are installation-specific; do not assume they use
  the earlier proposed .250.11/.250.12 addresses when they are actually on LAN1/LAN2.

Legacy RTU IDs 8020..8026 are internal software IDs for testbench/HMI, not TCP ports.
"""

HOST_SIMULATOR = "192.168.250.2"  # PC's physical Ethernet IP on S1
# Current HUe MNT interface used for CHFLISR Modbus TCP server.
# Confirm this matches the address configured on the actual Saitel HUe.
HOST_SAITEL_HUE = "192.168.250.1"
HOST_HUE_MODBUS = HOST_SAITEL_HUE
PORT_HUE_MODBUS = 502
# CHFLISR server-side Unit IDs from the uploaded NEWEST.ebc MDBE bins, in NODE order.
# 1=GIA, 2=GD01, 3=GD02, 4=GD03, 5=GD04, 6=GD05, 7=GIB.
HUE_UNIT_IDS = [1, 2, 3, 4, 5, 6, 7]

# Downstream Unit IDs from NEWEST.ebc -> C04 Files/mdbm/mdbm_comun.xml.
# The Python RTU simulators also expose Unit ID 1 for direct mode/testbench.
# NODE order: GIA, GD01, GD02, GD03, GD04, GD05, GIB.
RTU_MDBM_UNIT_IDS = [1, 2, 2, 3, 4, 2, 3]
TESTBENCH_EBC_UNIT_ID = 30  # M30_TestBench in NEWEST.ebc
TESTBENCH_LEGACY_UNIT_ID = 1  # HMI/system_behavior internal client
HOST_PLC1 = "192.168.251.11"         # physical Schneider TM221CE40R on HUe LAN1
HOST_PLC2 = "192.168.252.11"         # physical Schneider TM221CE16T on HUe LAN2
PORT_SAITEL_HUE = 502
PORT_PLC1 = 502
PORT_PLC2 = 502
# Backward-compatible alias for scripts that referenced the original single-PLC name.
HOST_PLC = HOST_PLC1
PORT_PLC = PORT_PLC1
PORT_WEB_HMI = 8501
PORT_SHG = 502                    # FLISR Controller Modbus TCP server
PORT_TESTBENCH = 503              # System Behavior / fault injection
SLAVE_RTU = 1

# Node tuple shape remains (name, TCP port, number of bays).
# The TCP port is 502 for every simulated RTU; identity is distinguished by IP.
NODE = [
    ("GI SATU", 502, 1),
    ("GD01",    502, 2),
    ("GD02",    502, 2),
    ("GD03",    502, 2),
    ("GD04",    502, 2),
    ("GD05",    502, 2),
    ("GI DUA",  502, 1),
]

# Addresses from the corrected network diagram. Index follows NODE order.
RTU_IPS = [
    "192.168.250.3",  # GI SATU / GI A
    "192.168.250.9",  # GD01
    "192.168.250.5",  # GD02
    "192.168.250.6",  # GD03
    "192.168.250.7",  # GD04
    "192.168.250.8",  # GD05
    "192.168.250.4",  # GI DUA / GI B
]

# Stable logical identifiers retained for existing GUI/testbench references.
RTU_LOGICAL_IDS = [8020, 8021, 8022, 8023, 8024, 8025, 8026]
RTU_ID_TO_NODE = {logical_id: idx for idx, logical_id in enumerate(RTU_LOGICAL_IDS)}

GI_KIRI = 0
GI_KANAN = 6
GARDU = [1, 2, 3, 4, 5]

SEGMEN = {
    0: ("GI SATU - GD01", (0, 0), (1, 0)),
    1: ("GD01 - GD02",    (1, 1), (2, 0)),
    2: ("GD02 - GD03",    (2, 1), (3, 0)),
    3: ("GD03 - GD04",    (3, 1), (4, 0)),
    4: ("GD04 - GD05",    (4, 1), (5, 0)),
    5: ("GD05 - GI DUA",  (5, 1), (6, 0)),
}

NOP = (3, 1)

BEBAN = {1: 45, 2: 50, 3: 40, 4: 35, 5: 30}
KAPASITAS_GI = 250

T_POLL = 1.0
T_KONFIRMASI = 1.0
T_JEDA_MANUVER = 0.3
T_SHG_TIMEOUT = 30.0

# Modbus function codes yang dipakai pymodbus.
CO = 1
DI = 2
HR = 3
IR = 4


# ---------- RTU gardu distribusi ----------
# FC01 coil-status image follows NEWEST.ebc MDBM_REQ FC=01 and CoreDb CS order.
# GD CS:0..9 = HFD1, CLOSE1, OPEN1, LOCAL1, REMOTE1,
#           HFD2, CLOSE2, OPEN2, LOCAL2, REMOTE2.
DI_GD_LBS1_HFD = 0
DI_GD_LBS1_CLOSE = 1
DI_GD_LBS1_OPEN = 2
DI_LBS1_LOCAL = 3
DI_LBS1_REMOTE = 4
DI_GD_LBS2_HFD = 5
DI_GD_LBS2_CLOSE = 6
DI_GD_LBS2_OPEN = 7
DI_LBS2_LOCAL = 8
DI_LBS2_REMOTE = 9
HR_SELECTOR_LBS1 = 5  # 0=LOCAL, 1=REMOTE
HR_SELECTOR_LBS2 = 6  # 0=LOCAL, 1=REMOTE

# ---------- RTU gardu induk ----------
# GI CS:0..5 = CBTR, CLOSE, OPEN, LOCAL, REMOTE, UV (FC01).
DI_CB_TRIP = 0
DI_CB_TUTUP = 1
DI_CB_BUKA = 2
DI_CB_LOCAL = 3
DI_CB_REMOTE = 4
DI_UV_GI = 5
HR_SELECTOR_CB = 4  # 0=LOCAL, 1=REMOTE

# ---------- Command coils on the Python RTU simulator (direct mode/testbench) ----------
# These are simulator-specific registers; EBC's CoreDb command coordinates are
# different and are handled by lapangan_hue.py / rtu_command_datablock.py.
CO_PERINTAH = 10
CO_RESET = 12

# ---------- CHFLISR server command-source addresses from CoreDb/Command ----------
# Existing source points in the supplied Excel: separate momentary OPEN/CLOSE.
HUE_CMD_GI_CLOSE = 1
HUE_CMD_GI_OPEN = 2
HUE_CMD_GD_LBS1_CLOSE = 1
HUE_CMD_GD_LBS1_OPEN = 2
HUE_CMD_GD_LBS2_CLOSE = 6
HUE_CMD_GD_LBS2_OPEN = 7
HUE_CMD_PULSE_SECONDS = 1.20  # longer than EBC 1-second MDBM scan period
HUE_FEEDBACK_TIMEOUT_SECONDS = 3.0  # EBC MDBM status scan interval is 1 s
# CoreDb Status points in the supplied workbook use CS: coordinates.
# Easergy Modbus Slave STD maps CS to FC01; FC02 reads IS coordinates.
HUE_STATUS_FC_PRIMARY = 1
HUE_STATUS_FORCE_FC = 1  # fixed for the supplied CS mapping

# Dedicated CoreDb command SOURCE coordinates for protection reset.
# The updated EBC project adds these source points outside the feedback range:
# GI CS:6 -> field RTU CS:0; GD CS:10 -> field CS:0; GD CS:11 -> field CS:5.
# Keep the runtime gate disabled by default. Enable only after the updated EBC
# has been sent to the HUe and the three mappings have been verified live.
HUE_RESET_SOURCE_GI = 6
HUE_RESET_SOURCE_GD1 = 10
HUE_RESET_SOURCE_GD2 = 11
HUE_RESET_SOURCE_MAP_AVAILABLE = os.getenv("FLISR_HUE_RESET_MAP", "0").strip().lower() in {"1", "true", "yes", "y"}

# ---------- Status controller -> HMI ----------
DI_SHG_ACTIVE = 0
DI_SHG_INPROGRESS = 1
DI_SHG_INCOMPLETE = 2
DI_RTU_ONLINE = 4          # 4..10
DI_SEMUA_ONLINE = 11
DI_KONFIG_NORMAL = 12
DI_LOCK_OUT = 13

# Telemetri detail controller -> HMI/HUe.
# 14..25  : posisi 12 switch (1=closed, 0=open)
# 26..35  : HFD 10 titik sensor GD (node 1..5, bay 0..1)
# 36..37  : trip GI kiri/kanan
# 38..44  : UV node 0..6
# 45..51  : OV node 0..6
# 52..63  : validitas posisi 12 switch
# 64..75  : selector Local feedback 12 switch
# 76..87  : selector Remote feedback 12 switch
# 88..99  : PLC-order switch-closed aliases (10 LBS then 2 CB)
DI_SWITCH_BASE = 14
DI_HFD_BASE = 26
DI_GI_TRIP_BASE = 36
DI_UV_NODE_BASE = 38
DI_OV_NODE_BASE = 45
DI_SWITCH_VALID_BASE = 52
# Selector feedback controller: first 12 Local bits, then 12 Remote bits.
DI_LR_LOCAL_BASE = 64
DI_LR_REMOTE_BASE = 76

# PLC status mapping on the shared Controller Modbus TCP server.
# PLC1 TM221CE40R: 12 switch-close outputs from DI88..DI99 plus first 4 HFDs DI26..DI29.
# PLC2 TM221CE16T: last 6 HFDs from DI30..DI35.
# Values for HFD are the existing telemetry/alarm bits (1 = active/true).
# Switch aliases are ON only for positively confirmed CLOSE with the owning RTU online.
DI_PLC_SWITCH_BASE = 88
DI_PLC_SWITCH_ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0, 11]
PLC1_SWITCH_DI_COUNT = 12
PLC1_HFD_DI_BASE = DI_HFD_BASE
PLC1_HFD_DI_COUNT = 4
PLC2_HFD_DI_BASE = DI_HFD_BASE + PLC1_HFD_DI_COUNT
PLC2_HFD_DI_COUNT = 6
JUMLAH_DI_CONTROLLER = 100

CO_SHG_ENABLE = 0
CO_RESET_LOCK_OUT = 1

IR_FASE = 0
IR_SASARAN = 1
IR_DETIK_MS = 2
IR_PADAM = 3
IR_KEJADIAN = 4
IR_RTU_ONLINE = 5

# Holding register khusus TEST/DEMO yang dilayani controller.
# HR0..HR5 = fault kabel segmen 0..5 (tulis 1 untuk trigger)
# HR6     = repair + kembalikan semua switch ke posisi normal
# HR7     = fault sumber (1=GI SATU, 2=GI DUA)
HR_FAULT_BASE = 0
HR_TEST_REPAIR = 6
HR_TEST_SOURCE = 7
JUMLAH_HR_CONTROLLER = 8

JUMLAH_DI_GI = 6
JUMLAH_DI_GD = 10

MENUNGGU_RTU = 0
DISABLE = 1
BELUM_SIAGA = 2
SIAGA = 3
LOKALISASI = 4
ISOLASI = 5
RESTORASI = 6
SELESAI = 7
SELESAI_SEBAGIAN = 8
LOCK_OUT = 9

NAMA_FASE = {
    MENUNGGU_RTU: "menunggu RTU",
    DISABLE: "SHG disable",
    BELUM_SIAGA: "kondisi awal belum terpenuhi",
    SIAGA: "siaga, memantau",
    LOKALISASI: "mencari lokasi",
    ISOLASI: "mengisolasi",
    RESTORASI: "memulihkan",
    SELESAI: "selesai",
    SELESAI_SEBAGIAN: "selesai sebagian",
    LOCK_OUT: "lock-out",
}


def nama_node(idx):
    return NODE[idx][0]


def mdbm_unit_id(idx):
    """Downstream Modbus Unit ID configured for this node in NEWEST.ebc."""
    return RTU_MDBM_UNIT_IDS[idx]


def hue_unit_id(idx):
    """CHFLISR Modbus Slave Unit ID configured for this node in NEWEST.ebc."""
    return HUE_UNIT_IDS[idx]


def hue_switch_command_address(node, bay, tutup):
    """Resolve the exact EBC CoreDb/Command source coil for a switch action."""
    if adalah_gardu_induk(node):
        if bay != 0:
            raise ValueError(f"GI hanya memiliki bay 0, bukan {bay}")
        return HUE_CMD_GI_CLOSE if tutup else HUE_CMD_GI_OPEN
    if bay == 0:
        return HUE_CMD_GD_LBS1_CLOSE if tutup else HUE_CMD_GD_LBS1_OPEN
    if bay == 1:
        return HUE_CMD_GD_LBS2_CLOSE if tutup else HUE_CMD_GD_LBS2_OPEN
    raise ValueError(f"Bay GD tidak valid: {bay}")


def hue_reset_source_addresses(node):
    """Return the reserved CHFLISR source coils required for reset routing."""
    return [HUE_RESET_SOURCE_GI] if adalah_gardu_induk(node) else [
        HUE_RESET_SOURCE_GD1, HUE_RESET_SOURCE_GD2
    ]


def port_node(idx):
    """Actual TCP port for the RTU; all simulated RTUs use Modbus TCP 502."""
    return NODE[idx][1]


def ip_node(idx):
    """Actual per-device IP for the RTU at NODE index idx."""
    return RTU_IPS[idx]


def endpoint_node(idx):
    """Return (IP, TCP port) for a physical virtual-RTU endpoint."""
    return ip_node(idx), port_node(idx)


def endpoint_logical_id(logical_id):
    """Resolve legacy software identifier 8020..8026 to (IP, TCP port)."""
    if logical_id not in RTU_ID_TO_NODE:
        raise KeyError(f"Unknown RTU logical ID: {logical_id}")
    return endpoint_node(RTU_ID_TO_NODE[logical_id])


def jumlah_bay(idx):
    return NODE[idx][2]


def adalah_gardu_induk(idx):
    return NODE[idx][2] == 1


def nama_bay(node, bay):
    if adalah_gardu_induk(node):
        return "CB " + nama_node(node)
    return "LBS%d %s" % (bay + 1, nama_node(node))


def bay_pengapit(segmen):
    _, kiri, kanan = SEGMEN[segmen]
    return kiri, kanan


def nama_segmen(segmen):
    return SEGMEN[segmen][0]


def semua_switch():
    """Daftar seluruh switch dalam urutan tetap untuk telemetri HMI."""
    hasil = []
    for node in range(len(NODE)):
        for bay in range(jumlah_bay(node)):
            hasil.append((node, bay))
    return hasil


def switch_index(node, bay):
    """Index 0..11 untuk telemetry posisi switch."""
    semua = semua_switch()
    try:
        return semua.index((node, bay))
    except ValueError:
        return -1
