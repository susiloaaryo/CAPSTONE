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

    def semua_online(self):
        return len(self.online) == len(T.NODE)


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
            print(f"[LAPANGAN] gagal konek RTU node {node} port {T.port_node(node)}: {e}")
            return False
        if not ok or not klien.connected:
            print(f"[LAPANGAN] RTU node {node} port {T.port_node(node)} tidak connected")
            return False
        return True

    async def sambung(self):
        """Buka sambungan awal ke semua RTU."""
        for idx in range(len(T.NODE)):
            klien = AsyncModbusTcpClient("127.0.0.1", port=T.port_node(idx))
            self.klien[idx] = klien
            await self._pastikan_tersambung(idx)

    async def baca(self):
        """Baca seluruh lapangan sekali dan kembalikan Potret."""
        data = Potret()

        for idx in range(len(T.NODE)):
            if not await self._pastikan_tersambung(idx):
                continue

            jumlah_bit = 5 if T.adalah_gardu_induk(idx) else 10
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
        """Baca tepat jumlah DI yang dimiliki RTU sesuai kontrak v3.

        GI menyediakan DI 0..4 (5 bit), sedangkan GD menyediakan DI 0..9
        (10 bit). Meminta terlalu banyak bit dari GI menyebabkan
        Exception Response(130, 2, IllegalAddress).
        """
        try:
            jawab = await klien.read_discrete_inputs(
                0, jumlah_bit, slave=T.SLAVE_RTU
            )
        except Exception as e:
            print(
                f"[LAPANGAN] read DI gagal node {node} "
                f"port {T.port_node(node)}: {e}"
            )
            return None

        if jawab is None:
            print(f"[LAPANGAN] read DI node {node} menghasilkan None")
            return None
        if jawab.isError():
            print(
                f"[LAPANGAN] read DI node {node} Modbus error: {jawab}"
            )
            return None
        if len(jawab.bits) < jumlah_bit:
            print(
                f"[LAPANGAN] DI node {node} kurang: "
                f"dapat {len(jawab.bits)}, butuh {jumlah_bit}"
            )
            return None
        return jawab.bits

    def _baca_gardu_induk(self, data, idx, bit):
        buka = self._bit_aman(bit, T.DI_CB_BUKA)
        tutup = self._bit_aman(bit, T.DI_CB_TUTUP)
        self._catat_posisi(data, idx, 0, buka, tutup)

        data.trip[idx] = self._bit_aman(bit, T.DI_CB_TRIP)
        data.under_voltage[idx] = self._bit_aman(bit, T.DI_UV_GI)
        data.over_voltage[idx] = self._bit_aman(bit, T.DI_OV_GI)

    def _baca_gardu_distribusi(self, data, idx, bit):
        for bay in (0, 1):
            dasar = 4 * bay
            buka = self._bit_aman(bit, dasar + T.DI_POSISI_BUKA)
            tutup = self._bit_aman(bit, dasar + T.DI_POSISI_TUTUP)
            self._catat_posisi(data, idx, bay, buka, tutup)
            data.hfd[(idx, bay)] = self._bit_aman(bit, dasar + T.DI_HFD)

        data.under_voltage[idx] = self._bit_aman(bit, T.DI_UV_GD)
        data.over_voltage[idx] = self._bit_aman(bit, T.DI_OV_GD)

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
        """Kirim command dan pastikan respons Modbus bukan error."""
        if not await self._pastikan_tersambung(node):
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
