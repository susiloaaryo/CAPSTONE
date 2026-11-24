"""LANGKAH 4 — Membaca dan memerintah tujuh RTU lewat Modbus.

Berkas ini adalah satu-satunya lapisan yang menyentuh jaringan. Semua
penalaran tetap bebas dari detail Modbus agar mudah diuji.
"""

import asyncio
import time

from pymodbus.client import AsyncModbusTcpClient

import topologi as T


class Potret:
    """Snapshot satu kali seluruh keadaan lapangan."""

    def __init__(self):
        self.posisi = {}          # (node, bay) -> True jika tertutup
        self.transit = set()      # (node, bay) sedang bergerak/tidak valid
        self.hfd = {}             # (node, bay) -> 0/1
        self.trip = {}            # node GI -> 0/1
        self.under_voltage = {}   # node -> 0/1
        self.over_voltage = {}    # node -> 0/1
        self.online = set()       # node yang menjawab
        self.lr_local = {}        # (node, bay) -> selector LOCAL feedback bit
        self.lr_remote = {}       # (node, bay) -> selector REMOTE feedback bit

    def semua_online(self):
        return len(self.online) == len(T.NODE)

    def semua_remote(self):
        """True only when all 12 switches explicitly report REMOTE (0,1)."""
        return all(
            self.lr_local.get(key) == 0 and self.lr_remote.get(key) == 1
            for key in T.semua_switch()
        )

    def jumlah_remote(self):
        return sum(
            self.lr_local.get(key) == 0 and self.lr_remote.get(key) == 1
            for key in T.semua_switch()
        )


class Lapangan:
    """Penghubung Modbus controller ke tujuh RTU."""

    def __init__(self):
        self.klien = {}

    async def _pastikan_tersambung(self, node):
        klien = self.klien[node]
        if klien.connected:
            return True
        try:
            ok = await klien.connect()
        except Exception as e:
            print(f"[LAPANGAN] gagal konek RTU node {node} di {T.ip_node(node)}:{T.port_node(node)}: {e}")
            return False
        if not ok or not klien.connected:
            print(f"[LAPANGAN] RTU node {node} di {T.ip_node(node)}:{T.port_node(node)} tidak connected")
            return False
        return True

    async def sambung(self):
        """Buka sambungan awal ke semua RTU."""
        for idx in range(len(T.NODE)):
            klien = AsyncModbusTcpClient(T.ip_node(idx), port=T.port_node(idx))
            self.klien[idx] = klien
            await self._pastikan_tersambung(idx)

    async def baca(self):
        """Baca seluruh lapangan sekali dan kembalikan Potret."""
        data = Potret()

        for idx in range(len(T.NODE)):
            if not await self._pastikan_tersambung(idx):
                continue

            jumlah_bit = T.JUMLAH_DI_GI if T.adalah_gardu_induk(idx) else T.JUMLAH_DI_GD
            bit = await self._baca_bit(self.klien[idx], jumlah_bit, idx)
            if bit is None:
                continue

            data.online.add(idx)

            if T.adalah_gardu_induk(idx):
                self._baca_gardu_induk(data, idx, bit)
            else:
                self._baca_gardu_distribusi(data, idx, bit)

        return data

    async def _baca_bit(self, klien, jumlah_bit, node):
        """Baca DI yang diperlukan tanpa memakai UV/OV milik GD.

        Status switch/proteksi kini dipublikasikan simulator pada FC01:
        GI CO0..CO5 dan GD CO0..CO9. Pembacaan dilakukan satu blok
        berurutan sesuai jumlah status masing-masing RTU.
        """
        if not T.adalah_gardu_induk(node) and jumlah_bit >= T.JUMLAH_DI_GD:
            rentang = [(0, jumlah_bit)]
            bit = [0] * jumlah_bit
        else:
            rentang = [(0, jumlah_bit)]
            bit = [0] * jumlah_bit

        for alamat, banyak in rentang:
            try:
                jawab = await klien.read_coils(
                    alamat, banyak, slave=T.SLAVE_RTU
                )
            except Exception as e:
                print(
                    f"[LAPANGAN] read COIL gagal node {node} "
                    f"alamat {alamat}..{alamat + banyak - 1}: {e}"
                )
                return None

            if jawab is None:
                print(
                    f"[LAPANGAN] read COIL node {node} alamat {alamat} "
                    "menghasilkan None"
                )
                return None
            if jawab.isError():
                print(
                    f"[LAPANGAN] read COIL node {node} "
                    f"alamat {alamat}..{alamat + banyak - 1} Modbus error: {jawab}"
                )
                return None
            if len(jawab.bits) < banyak:
                print(
                    f"[LAPANGAN] COIL node {node} alamat {alamat}.."
                    f"{alamat + banyak - 1} kurang: dapat {len(jawab.bits)}, "
                    f"butuh {banyak}"
                )
                return None
            bit[alamat:alamat + banyak] = [int(v) for v in jawab.bits[:banyak]]

        return bit

    def _baca_gardu_induk(self, data, idx, bit):
        # EBC GI CS:0=CBTR, 1=CLOSE, 2=OPEN, 3=LOCAL, 4=REMOTE, 5=UV.
        buka = self._bit_aman(bit, T.DI_CB_BUKA)
        tutup = self._bit_aman(bit, T.DI_CB_TUTUP)
        self._catat_posisi(data, idx, 0, buka, tutup)
        data.trip[idx] = self._bit_aman(bit, T.DI_CB_TRIP)
        data.under_voltage[idx] = self._bit_aman(bit, T.DI_UV_GI)
        data.over_voltage[idx] = 0
        data.lr_local[(idx, 0)] = self._bit_aman(bit, T.DI_CB_LOCAL)
        data.lr_remote[(idx, 0)] = self._bit_aman(bit, T.DI_CB_REMOTE)

    def _baca_gardu_distribusi(self, data, idx, bit):
        # EBC GD CS:0..9 follows the two LBS bays, not the former DI layout.
        buka1 = self._bit_aman(bit, T.DI_GD_LBS1_OPEN)
        tutup1 = self._bit_aman(bit, T.DI_GD_LBS1_CLOSE)
        buka2 = self._bit_aman(bit, T.DI_GD_LBS2_OPEN)
        tutup2 = self._bit_aman(bit, T.DI_GD_LBS2_CLOSE)
        self._catat_posisi(data, idx, 0, buka1, tutup1)
        self._catat_posisi(data, idx, 1, buka2, tutup2)
        data.hfd[(idx, 0)] = self._bit_aman(bit, T.DI_GD_LBS1_HFD)
        data.hfd[(idx, 1)] = self._bit_aman(bit, T.DI_GD_LBS2_HFD)
        data.lr_local[(idx, 0)] = self._bit_aman(bit, T.DI_LBS1_LOCAL)
        data.lr_local[(idx, 1)] = self._bit_aman(bit, T.DI_LBS2_LOCAL)
        data.lr_remote[(idx, 0)] = self._bit_aman(bit, T.DI_LBS1_REMOTE)
        data.lr_remote[(idx, 1)] = self._bit_aman(bit, T.DI_LBS2_REMOTE)

    @staticmethod
    def _bit_aman(bit, alamat):
        if alamat < 0 or alamat >= len(bit):
            return 0
        return int(bit[alamat])

    @staticmethod
    def _catat_posisi(data, idx, bay, buka, tutup):
        """Terjemahkan Double Point.

        0,1 = tertutup
        1,0 = terbuka
        0,0 / 1,1 = posisi tidak valid/tidak diketahui
        """
        if (buka, tutup) == (0, 1):
            data.posisi[(idx, bay)] = True
        elif (buka, tutup) == (1, 0):
            data.posisi[(idx, bay)] = False
        else:
            data.transit.add((idx, bay))

    async def kirim_perintah(self, node, bay, tutup):
        """Kirim command hanya jika selector switch dikonfirmasi REMOTE."""
        if not await self._pastikan_tersambung(node):
            return False

        # Cek feedback aktual tepat sebelum menulis coil. RTU juga menerapkan
        # interlock lokal sehingga race kecil antara pemeriksaan dan write aman.
        jumlah_bit = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
        bit = await self._baca_bit(self.klien[node], jumlah_bit, node)
        if bit is None:
            return False
        if T.adalah_gardu_induk(node):
            local_idx, remote_idx = T.DI_CB_LOCAL, T.DI_CB_REMOTE
        elif bay == 0:
            local_idx, remote_idx = T.DI_LBS1_LOCAL, T.DI_LBS1_REMOTE
        else:
            local_idx, remote_idx = T.DI_LBS2_LOCAL, T.DI_LBS2_REMOTE
        if self._bit_aman(bit, local_idx) != 0 or self._bit_aman(bit, remote_idx) != 1:
            print(
                f"[LAPANGAN] command {T.nama_bay(node, bay)} ditolak: "
                "selector tidak terkonfirmasi REMOTE"
            )
            return False

        try:
            jawab = await self.klien[node].write_coil(
                T.CO_PERINTAH + bay,
                bool(tutup),
                slave=T.SLAVE_RTU,
            )
        except Exception:
            return False
        if jawab is None:
            print(f"[LAPANGAN] write coil gagal: response None")
            return False
        if jawab.isError():
            print(f"[LAPANGAN] write coil Modbus error: {jawab}")
            return False
        return True

    async def kirim_reset(self, node):
        """Pulsa coil reset untuk HFD (GD) atau trip (GI)."""
        if not await self._pastikan_tersambung(node):
            return False
        try:
            jawab = await self.klien[node].write_coil(T.CO_RESET, True, slave=T.SLAVE_RTU)
        except Exception:
            return False
        if jawab is None:
            print("[LAPANGAN] reset coil gagal: response None")
            return False
        if jawab.isError():
            print(f"[LAPANGAN] reset coil Modbus error: {jawab}")
            return False
        return True

    async def tunggu_posisi(self, node, bay, harus_tertutup, batas=None):
        """Tunggu posisi target terkonfirmasi sampai timeout."""
        if batas is None:
            batas = T.T_KONFIRMASI

        mulai = time.monotonic()
        while time.monotonic() - mulai < batas:
            await asyncio.sleep(0.05)
            data = await self.baca()
            if data.posisi.get((node, bay)) == harus_tertutup:
                return True
        return False
