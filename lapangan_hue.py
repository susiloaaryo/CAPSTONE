"""Field adapter for FLISR through the Easergy Builder HUe project.

CHFLISR is the HUe Modbus TCP server at 192.168.250.1:502. Its seven
MDBE logical devices use Unit IDs 1..7. The supplied CoreDb workbook maps the
field status image to CS:0..5 (GI) and CS:0..9 (GD). In the Easergy Modbus
Slave STD profile, CS is read using FC01 and written using FC05. FC02 is for
IS coordinates and is not a valid fallback for this CS map.

A Modbus timeout can cause pymodbus to mark the TCP client disconnected. A
fresh client is created before the next node/read so one failed request does
not make all later Unit IDs fail with "Not connected".

Protection reset still requires SOURCE_COORD entries absent from the supplied
CoreDb Command worksheet. The adapter will not write to unconfigured reset
coordinates and verifies feedback before reporting success.
"""

import asyncio
import time

from pymodbus.client import AsyncModbusTcpClient

import topologi as T
from lapangan import Lapangan


class LapanganHue(Lapangan):
    """Same field API as Lapangan, routed through one HUe CHFLISR connection."""

    def __init__(self):
        super().__init__()
        self._client = None
        self._retry_after = 0.0
        self._connect_backoff_s = 2.0
        self._status_function_by_unit = {}
        # One CHFLISR TCP client is shared by all seven logical devices.
        self._io_lock = asyncio.Lock()

    def _unit_id(self, node):
        try:
            return T.hue_unit_id(node)
        except (IndexError, TypeError) as exc:
            raise ValueError(
                f"Unit ID CHFLISR tidak dikonfigurasi untuk node {node}"
            ) from exc

    def _buat_client(self):
        """Create one clean TCP client and refresh all shared client aliases."""
        self._client = AsyncModbusTcpClient(
            T.HOST_HUE_MODBUS,
            port=T.PORT_HUE_MODBUS,
            timeout=3,
            retries=0,
        )
        self.klien = {idx: self._client for idx in range(len(T.NODE))}

    async def sambung(self):
        """Connect to CHFLISR and probe all seven logical Unit IDs."""
        if not await self._pastikan_tersambung(0):
            return

        for node in range(len(T.NODE)):
            count = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
            bits = await self._baca_bit(self._client, count, node)
            if bits is None:
                print(
                    f"[LAPANGAN-HUE] [FAIL] {T.nama_node(node)} Unit ID "
                    f"{self._unit_id(node)}: FC01 CS:0..{count - 1} belum terbaca; "
                    "koneksi akan dicoba ulang pada polling berikutnya."
                )
            else:
                print(
                    f"[LAPANGAN-HUE] [PASS] {T.nama_node(node)} Unit ID "
                    f"{self._unit_id(node)}: FC01, {count} point terbaca"
                )

    async def _pastikan_tersambung(self, node):
        """Reconnect with a fresh client after a transport timeout."""
        if self._client is not None and self._client.connected:
            return True

        now = time.monotonic()
        if now < self._retry_after:
            return False

        # Recreate rather than reusing a client whose transport may have been
        # closed internally by pymodbus after a no-response timeout.
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._buat_client()

        try:
            ok = await self._client.connect()
        except Exception as exc:
            self._retry_after = time.monotonic() + self._connect_backoff_s
            print(
                f"[LAPANGAN-HUE] gagal konek HUe "
                f"{T.HOST_HUE_MODBUS}:{T.PORT_HUE_MODBUS}: {exc}"
            )
            return False

        if not ok or not self._client.connected:
            self._retry_after = time.monotonic() + self._connect_backoff_s
            print(
                f"[LAPANGAN-HUE] HUe belum reachable di "
                f"{T.HOST_HUE_MODBUS}:{T.PORT_HUE_MODBUS}; "
                "akan mencoba ulang otomatis."
            )
            return False

        # A successful connection must not leave a stale retry backoff active.
        self._retry_after = 0.0
        print(
            f"[LAPANGAN-HUE] terkoneksi ke HUe "
            f"{T.HOST_HUE_MODBUS}:{T.PORT_HUE_MODBUS}"
        )
        return True

    async def baca(self):
        """Read the seven logical devices without interleaving shared-client IO."""
        async with self._io_lock:
            return await super().baca()

    async def tunggu_posisi(self, node, bay, harus_tertutup, batas=None):
        """Allow for the 1-second EBC scan before declaring a switch timeout."""
        if batas is None:
            batas = T.HUE_FEEDBACK_TIMEOUT_SECONDS
        return await super().tunggu_posisi(node, bay, harus_tertutup, batas=batas)

    async def _baca_bit(self, klien, jumlah_bit, node):
        """Read the CoreDb CS image with FC01 (the mapped data type)."""
        if not await self._pastikan_tersambung(node):
            return None

        unit_id = self._unit_id(node)
        try:
            jawab = await self._client.read_coils(
                address=0, count=jumlah_bit, slave=unit_id
            )
        except Exception as exc:
            connected = bool(self._client and self._client.connected)
            print(
                f"[LAPANGAN-HUE] FC01 read gagal {T.nama_node(node)} "
                f"Unit ID {unit_id} CS:0..{jumlah_bit - 1}: {exc}; "
                f"socket_connected={connected}."
            )
            # Treat a no-response read as a broken session even if the
            # underlying client still reports connected. The next node/read
            # will create a fresh TCP client instead of reusing this socket.
            try:
                self._client.close()
            except Exception:
                pass
            self._status_function_by_unit.pop(unit_id, None)
            return None

        if jawab is None or jawab.isError():
            print(
                f"[LAPANGAN-HUE] FC01 Modbus response error {T.nama_node(node)} "
                f"Unit ID {unit_id} CS:0..{jumlah_bit - 1}: {jawab}"
            )
            return None
        if len(jawab.bits) < jumlah_bit:
            print(
                f"[LAPANGAN-HUE] FC01 {T.nama_node(node)} Unit ID {unit_id}: "
                f"hanya {len(jawab.bits)} bit, perlu {jumlah_bit}"
            )
            return None

        self._status_function_by_unit[unit_id] = 1
        return [int(value) for value in jawab.bits[:jumlah_bit]]

    async def kirim_perintah(self, node, bay, tutup):
        async with self._io_lock:
            return await self._kirim_perintah_locked(node, bay, tutup)

    async def _kirim_perintah_locked(self, node, bay, tutup):
        """Pulse the exact OPEN/CLOSE source point defined in CoreDb/Command."""
        if not await self._pastikan_tersambung(node):
            return False

        jumlah_bit = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
        bit = await self._baca_bit(self._client, jumlah_bit, node)
        if bit is None:
            return False

        if T.adalah_gardu_induk(node):
            local_idx, remote_idx = T.DI_CB_LOCAL, T.DI_CB_REMOTE
        elif bay == 0:
            local_idx, remote_idx = T.DI_LBS1_LOCAL, T.DI_LBS1_REMOTE
        elif bay == 1:
            local_idx, remote_idx = T.DI_LBS2_LOCAL, T.DI_LBS2_REMOTE
        else:
            print(f"[LAPANGAN-HUE] bay tidak valid: {T.nama_node(node)} bay={bay}")
            return False

        if self._bit_aman(bit, local_idx) != 0 or self._bit_aman(bit, remote_idx) != 1:
            print(
                f"[LAPANGAN-HUE] command {T.nama_bay(node, bay)} ditolak: "
                f"selector belum terkonfirmasi REMOTE melalui HUe "
                f"(Unit ID {self._unit_id(node)})"
            )
            return False

        try:
            address = T.hue_switch_command_address(node, bay, bool(tutup))
        except ValueError as exc:
            print(f"[LAPANGAN-HUE] {exc}")
            return False

        action = "CLOSE" if tutup else "OPEN"
        unit_id = self._unit_id(node)
        asserted = False
        cleared = False
        try:
            response = await self._client.write_coil(address, True, slave=unit_id)
            if response is None or response.isError():
                print(
                    f"[LAPANGAN-HUE] {action} {T.nama_bay(node, bay)} "
                    f"ditolak HUe: Unit ID {unit_id}, FC05 coil {address}: {response}"
                )
                return False
            asserted = True
            await asyncio.sleep(T.HUE_CMD_PULSE_SECONDS)
            clear = await self._client.write_coil(address, False, slave=unit_id)
            if clear is None or clear.isError():
                print(
                    f"[LAPANGAN-HUE] gagal melepas pulse {action} "
                    f"{T.nama_bay(node, bay)} pada coil {address}: {clear}"
                )
                return False
            cleared = True
        except Exception as exc:
            print(
                f"[LAPANGAN-HUE] write {action} {T.nama_bay(node, bay)} "
                f"gagal pada Unit ID {unit_id} coil {address}: {exc}"
            )
            return False
        finally:
            if asserted and not cleared:
                try:
                    await self._client.write_coil(address, False, slave=unit_id)
                except Exception:
                    pass

        print(
            f"[LAPANGAN-HUE] pulse {action} {T.nama_bay(node, bay)} "
            f"-> CHFLISR Unit ID {unit_id}, FC05 coil {address}"
        )
        return True

    async def _pulse_reset_source(self, node, address):
        """Pulse a dedicated CHFLISR reset-source coil and always clear it."""
        unit_id = self._unit_id(node)
        asserted = False
        cleared = False
        try:
            response = await self._client.write_coil(address, True, slave=unit_id)
            if response is None or response.isError():
                print(
                    f"[LAPANGAN-HUE] reset belum terpetakan di CoreDb: "
                    f"{T.nama_node(node)} Unit ID {unit_id}, "
                    f"FC05 coil {address}: {response}"
                )
                return False
            asserted = True
            await asyncio.sleep(T.HUE_CMD_PULSE_SECONDS)
            clear = await self._client.write_coil(address, False, slave=unit_id)
            if clear is None or clear.isError():
                print(
                    f"[LAPANGAN-HUE] reset pulse gagal dilepas: "
                    f"{T.nama_node(node)} coil {address}: {clear}"
                )
                return False
            cleared = True
            return True
        except Exception as exc:
            print(
                f"[LAPANGAN-HUE] reset write gagal {T.nama_node(node)} "
                f"Unit ID {unit_id}, coil {address}: {exc}"
            )
            return False
        finally:
            if asserted and not cleared:
                try:
                    await self._client.write_coil(address, False, slave=unit_id)
                except Exception:
                    pass

    async def kirim_reset(self, node):
        async with self._io_lock:
            return await self._kirim_reset_locked(node)

    async def _kirim_reset_locked(self, node):
        """Reset trip/HFD through dedicated CoreDb sources, then verify status.

        The updated CoreDb project maps dedicated CHFLISR source coils to the
        field reset destinations. Runtime writes remain fail-safe: they are
        disabled unless FLISR_HUE_RESET_MAP=1 is explicitly set after the
        updated EBC has been sent to the HUe and verified on the live endpoint.
        """
        if not await self._pastikan_tersambung(node):
            return False

        jumlah_bit = T.JUMLAH_DI_GI if T.adalah_gardu_induk(node) else T.JUMLAH_DI_GD
        current = await self._baca_bit(self._client, jumlah_bit, node)
        if current is None:
            return False
        if T.adalah_gardu_induk(node):
            needs_reset = self._bit_aman(current, T.DI_CB_TRIP) == 1
        else:
            needs_reset = (
                self._bit_aman(current, T.DI_GD_LBS1_HFD) == 1
                or self._bit_aman(current, T.DI_GD_LBS2_HFD) == 1
            )
        if not needs_reset:
            print(
                f"[LAPANGAN-HUE] {T.nama_node(node)} tidak memiliki latch trip/HFD aktif; "
                "reset tidak diperlukan."
            )
            return True

        if not T.HUE_RESET_SOURCE_MAP_AVAILABLE:
            print(
                f"[LAPANGAN-HUE] reset {T.nama_node(node)} tidak dikirim: "
                "pemetaan reset belum diaktifkan. Kirim EBC reset-mapped ke HUe, "
                "verifikasi CS6/CS10/CS11, lalu set FLISR_HUE_RESET_MAP=1."
            )
            return False

        addresses = T.hue_reset_source_addresses(node)
        sent = []
        for address in addresses:
            sent.append(await self._pulse_reset_source(node, address))
        if not all(sent):
            print(
                f"[LAPANGAN-HUE] reset {T.nama_node(node)} gagal: "
                "CoreDb reset source belum lengkap/terkonfigurasi."
            )
            return False

        deadline = time.monotonic() + T.HUE_FEEDBACK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(0.10)
            bit = await self._baca_bit(self._client, jumlah_bit, node)
            if bit is None:
                return False
            if T.adalah_gardu_induk(node):
                cleared = self._bit_aman(bit, T.DI_CB_TRIP) == 0
            else:
                cleared = (
                    self._bit_aman(bit, T.DI_GD_LBS1_HFD) == 0
                    and self._bit_aman(bit, T.DI_GD_LBS2_HFD) == 0
                )
            if cleared:
                print(f"[LAPANGAN-HUE] reset {T.nama_node(node)} terkonfirmasi via FC01.")
                return True

        print(
            f"[LAPANGAN-HUE] reset {T.nama_node(node)} tidak terkonfirmasi; "
            "status trip/HFD masih aktif. Periksa CoreDb Command source dan MDBM output."
        )
        return False

    async def tutup(self):
        """Close the single HUe TCP connection if the caller stops."""
        if self._client is not None:
            self._client.close()
