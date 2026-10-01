"""Peta jaringan dan kontrak alamat Modbus untuk simulasi FLISR."""

NODE = [
    ("GI SATU", 8020, 1),
    ("GD01",    8021, 2),
    ("GD02",    8022, 2),
    ("GD03",    8023, 2),
    ("GD04",    8024, 2),
    ("GD05",    8025, 2),
    ("GI DUA",  8026, 1),
]

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

PORT_SHG = 503
SLAVE_RTU = 1           # seluruh RTU simulator menggunakan Slave ID 1

# ---------- RTU gardu distribusi ----------
DI_POSISI_BUKA = 0
DI_POSISI_TUTUP = 1
DI_HFD = 2
DI_UV_GD = 8
DI_OV_GD = 9

# ---------- RTU gardu induk ----------
DI_CB_BUKA = 0
DI_CB_TUTUP = 1
DI_CB_TRIP = 2
DI_UV_GI = 3
DI_OV_GI = 4

# ---------- Coil command RTU ----------
CO_PERINTAH = 0
CO_RESET = 2

# ---------- Status controller -> HMI ----------
DI_SHG_ACTIVE = 0
DI_SHG_INPROGRESS = 1
DI_SHG_INCOMPLETE = 2
DI_RTU_ONLINE = 4          # 4..10
DI_SEMUA_ONLINE = 11
DI_KONFIG_NORMAL = 12
DI_LOCK_OUT = 13

# Telemetri detail controller -> HMI.
# 14..25  : posisi 12 switch (1=closed, 0=open)
# 26..35  : HFD 10 titik sensor GD (node 1..5, bay 0..1)
# 36..37  : trip GI kiri/kanan
# 38..44  : UV node 0..6
# 45..51  : OV node 0..6
# 52..63  : validitas posisi 12 switch
DI_SWITCH_BASE = 14
DI_HFD_BASE = 26
DI_GI_TRIP_BASE = 36
DI_UV_NODE_BASE = 38
DI_OV_NODE_BASE = 45
DI_SWITCH_VALID_BASE = 52
JUMLAH_DI_CONTROLLER = 64

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

JUMLAH_DI_GI = 5
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


def port_node(idx):
    return NODE[idx][1]


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
