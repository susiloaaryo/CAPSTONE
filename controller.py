"""LANGKAH 5 — Program utama algoritma FLISR.

Berkas ini yang dijalankan. Tugasnya merangkai empat berkas sebelumnya
jadi satu siklus yang berjalan terus tiap satu detik.

Program ini punya DUA peran sekaligus, dan itu wajar:

  1. Sebagai CLIENT  -> dia yang bertanya dan memerintah tujuh RTU
  2. Sebagai SERVER  -> HMI yang bertanya status SHG ke dia, di port 503

Jalankan:  python controller.py

Sebelum menjalankan ini, simulator harus sudah hidup lebih dulu —
tujuh RTU di port 8020 sampai 8026.
"""

import asyncio
import csv
import logging
import os
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

import topologi as T
import penalaran as P
import lokalisasi as L
from lapangan import Lapangan

# Atur bentuk pesan yang muncul di layar: jam, tingkat, lalu isinya.
logging.basicConfig(
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)

# Berkas catatan peristiwa, dibuat di folder yang sama dengan berkas ini.
BERKAS_SOE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soe.csv")


class Controller:

    def __init__(self):
        self.lapangan = Lapangan()

        # --- Ingatan yang dibawa dari satu siklus ke siklus berikutnya ---
        self.lock_out = False   # sekali True, berhenti sampai operator reset
        self.siaga = False      # nilai Active yang DIKUNCI di siklus tenang
        self.kejadian = 0       # pencacah, naik tiap satu penanganan selesai

        # State fault injection untuk HMI/testbench.
        self.uji_fault_segmen = None
        self.uji_fault_sumber = None

        # Nilai yang dilaporkan ke HMI.
        self.fase = T.MENUNGGU_RTU
        self.sasaran = 0
        self.detik = 0.0
        self.padam = 0

        # --- Kotak-kotak Modbus yang controller layani di port 503 ---
        # zero_mode=True penting sekali. Tanpa itu pymodbus menambah 1
        # ke setiap alamat yang masuk, dan seluruh peta register bergeser.
        self.store = ModbusSlaveContext(
            di=ModbusSequentialDataBlock(0, [0] * T.JUMLAH_DI_CONTROLLER),
            co=ModbusSequentialDataBlock(0, [1] + [0] * 7),  # coil 0 = enable, menyala
            hr=ModbusSequentialDataBlock(0, [0] * T.JUMLAH_HR_CONTROLLER),
            ir=ModbusSequentialDataBlock(0, [0] * 8),
            zero_mode=True,
        )
        self.context = ModbusServerContext(slaves=self.store, single=True)

        self._siapkan_soe()

    # ==============================================================
    # CATATAN PERISTIWA (Sequence of Events)
    # ==============================================================

    def _siapkan_soe(self):
        """Buat berkas soe.csv beserta baris judulnya, kalau belum ada."""
        if not os.path.exists(BERKAS_SOE):
            with open(BERKAS_SOE, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["waktu", "tahap", "keterangan", "detik"])

    def catat(self, tahap, keterangan, detik=""):
        """Tulis satu baris peristiwa dengan cap waktu.

        Inilah tempat "complete" benar-benar tercatat. Bit alarm hanya
        lampu di panel; ceritanya ada di berkas ini.
        """
        with open(BERKAS_SOE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [time.strftime("%Y-%m-%d %H:%M:%S"), tahap, keterangan, detik]
            )

    # ==============================================================
    # MENERBITKAN STATUS UNTUK HMI
    # ==============================================================

    def baca_coil(self, alamat):
        """Baca satu coil yang ditulis HMI ke controller ini."""
        return bool(self.context[0].getValues(T.CO, alamat, count=1)[0])

    def tulis_coil(self, alamat, nilai):
        self.context[0].setValues(T.CO, alamat, [int(nilai)])

    def baca_hr(self, alamat, count=1):
        return self.context[0].getValues(T.HR, alamat, count=count)

    def tulis_hr(self, alamat, nilai):
        self.context[0].setValues(T.HR, alamat, [int(nilai)])

    def terbitkan_shg(self, aktif, berjalan, tidak_lengkap):
        """Isi tiga bit sinyal SHG yang dibaca HMI."""
        self.context[0].setValues(
            T.DI, T.DI_SHG_ACTIVE,
            [int(aktif), int(berjalan), int(tidak_lengkap)],
        )

    def terbitkan_online(self, data):
        """Terbitkan status online dan telemetri detail untuk HMI."""
        bit = [1 if i in data.online else 0 for i in range(len(T.NODE))]
        self.context[0].setValues(T.DI, T.DI_RTU_ONLINE, bit)

        self.context[0].setValues(
            T.DI, T.DI_SEMUA_ONLINE, [int(data.semua_online())]
        )
        self.context[0].setValues(
            T.DI, T.DI_KONFIG_NORMAL, [int(P.konfigurasi_normal(data.posisi))]
        )
        self.context[0].setValues(T.DI, T.DI_LOCK_OUT, [int(self.lock_out)])
        self.context[0].setValues(T.IR, T.IR_RTU_ONLINE, [len(data.online)])

        # Posisi seluruh switch. Valid=0 berarti transit/tidak diketahui.
        for idx, (node, bay) in enumerate(T.semua_switch()):
            closed = data.posisi.get((node, bay))
            self.context[0].setValues(
                T.DI, T.DI_SWITCH_BASE + idx,
                [int(closed)] if closed is not None else [0],
            )
            self.context[0].setValues(
                T.DI, T.DI_SWITCH_VALID_BASE + idx,
                [int(closed is not None)],
            )

        # Dua HFD per gardu distribusi.
        for offset, node in enumerate(T.GARDU):
            self.context[0].setValues(
                T.DI, T.DI_HFD_BASE + offset * 2,
                [int(data.hfd.get((node, 0), 0))],
            )
            self.context[0].setValues(
                T.DI, T.DI_HFD_BASE + offset * 2 + 1,
                [int(data.hfd.get((node, 1), 0))],
            )

        for offset, node in enumerate((T.GI_KIRI, T.GI_KANAN)):
            self.context[0].setValues(
                T.DI, T.DI_GI_TRIP_BASE + offset,
                [int(data.trip.get(node, 0))],
            )

        for node in range(len(T.NODE)):
            self.context[0].setValues(
                T.DI, T.DI_UV_NODE_BASE + node,
                [int(data.under_voltage.get(node, 0))],
            )
            self.context[0].setValues(
                T.DI, T.DI_OV_NODE_BASE + node,
                [int(data.over_voltage.get(node, 0))],
            )

    def lapor(self, fase, sasaran=None, detik=None, padam=None):
        """Perbarui input register supaya HMI bisa mengikuti tiap tahap.

        Dipanggil di SETIAP pergantian tahap, bukan hanya di akhir.
        Kalau hanya di akhir, HMI tidak akan pernah sempat menampilkan
        tahap isolasi dan restorasi — keduanya terlalu cepat.
        """
        self.fase = fase
        if sasaran is not None:
            self.sasaran = sasaran
        if detik is not None:
            self.detik = detik
        if padam is not None:
            self.padam = padam

        self.context[0].setValues(
            T.IR, T.IR_FASE,
            [
                self.fase,
                self.sasaran,
                int(self.detik * 1000),   # detik diubah jadi milidetik
                self.padam,
                self.kejadian,
            ],
        )

    # ==============================================================
    # PROSES I — ISOLASI
    # ==============================================================

    async def isolasi(self, data, segmen, dari_kiri):
        """Buka dua saklar yang mengapit kabel rusak.

        Kembaliannya True kalau keduanya terkonfirmasi terbuka.
        """
        kiri, kanan = T.bay_pengapit(segmen)

        # Aturan I3: yang JAUH dari sumber dibuka lebih dulu.
        # Alasannya menyangkut tahap berikutnya — waktu NOP ditutup,
        # arus datang dari arah berlawanan. Kalau saklar yang jauh
        # belum terbuka, arus bisa masuk ke kabel yang rusak.
        if dari_kiri:
            jauh, dekat = kanan, kiri
        else:
            jauh, dekat = kiri, kanan

        for node, bay in (jauh, dekat):
            # Aturan I2: CB gardu induk tidak dibuka FLISR.
            # Dia sudah terbuka sendiri oleh relai proteksi.
            if T.adalah_gardu_induk(node):
                continue

            # Aturan I8: yang sudah terbuka tidak diperintah lagi.
            if not P.tertutup(data.posisi, node, bay):
                logging.info("      %s sudah terbuka", T.nama_bay(node, bay))
                continue

            logging.info("      buka %s", T.nama_bay(node, bay))
            if not await self.lapangan.kirim_perintah(node, bay, tutup=False):
                logging.error("      command buka %s gagal", T.nama_bay(node, bay))
                self.catat("isolasi", "command buka gagal " + T.nama_bay(node, bay))
                return False

            # Aturan I5: jangan percaya perintah, tunggu buktinya.
            terbuka = await self.lapangan.tunggu_posisi(node, bay, False)
            if not terbuka:
                logging.error("      %s GAGAL terbuka", T.nama_bay(node, bay))
                self.catat("isolasi", "gagal membuka " + T.nama_bay(node, bay))
                return False

            # Aturan I7: beri jeda sebelum manuver berikutnya.
            await asyncio.sleep(T.T_JEDA_MANUVER)

        return True

    async def reset_hfd_aktif(self, data):
        """Reset HFD aktif dan verifikasi bahwa latch benar-benar clear."""
        node_hfd = sorted({
            node for (node, _bay), aktif in data.hfd.items() if aktif
        })
        semua_ok = True

        for node in node_hfd:
            logging.info("      reset HFD %s", T.nama_node(node))
            if not await self.lapangan.kirim_reset(node):
                logging.error("      reset HFD %s gagal dikirim", T.nama_node(node))
                semua_ok = False
                continue

            mulai = time.monotonic()
            clear = False
            while time.monotonic() - mulai < T.T_KONFIRMASI + T.T_POLL:
                await asyncio.sleep(0.05)
                cek = await self.lapangan.baca()
                masih_aktif = any(
                    cek.hfd.get((node, bay), 0)
                    for bay in range(T.jumlah_bay(node))
                )
                if not masih_aktif:
                    clear = True
                    break

            if not clear:
                logging.warning(
                    "      HFD %s masih aktif setelah reset",
                    T.nama_node(node),
                )
                semua_ok = False

        return semua_ok

    async def reset_trip_gi(self, gi):
        """Reset trip GI dan tunggu sampai bit trip benar-benar clear."""
        logging.info("      reset trip %s", T.nama_node(gi))
        if not await self.lapangan.kirim_reset(gi):
            logging.error("      reset trip %s gagal dikirim", T.nama_node(gi))
            return False

        mulai = time.monotonic()
        while time.monotonic() - mulai < T.T_KONFIRMASI + T.T_POLL:
            await asyncio.sleep(0.05)
            cek = await self.lapangan.baca()
            if not cek.trip.get(gi, 0):
                return True

        logging.warning("      trip %s masih aktif setelah reset", T.nama_node(gi))
        return False

    # ==============================================================
    # PROSES R — RESTORASI
    # ==============================================================

    async def restorasi(self, gi_trip, segmen_rusak):
        """Nyalakan kembali gardu sehat tanpa menghidupkan kabel rusak."""
        data = await self.lapangan.baca()

        # --- Bagian 1: pulihkan CB GI yang trip bila bukan pengapit fault ---
        pengapit = T.bay_pengapit(segmen_rusak)
        cb_mengapit = (gi_trip, 0) in pengapit

        if cb_mengapit:
            logging.info(
                "      %s mengapit kabel rusak, tidak ditutup",
                T.nama_bay(gi_trip, 0),
            )
        else:
            # CB yang trip harus di-reset dulu sebelum dapat ditutup.
            if data.trip.get(gi_trip, 0):
                if not await self.reset_trip_gi(gi_trip):
                    self.catat("restorasi", "gagal reset trip " + T.nama_node(gi_trip))
                    return False

                data = await self.lapangan.baca()

            if not P.tertutup(data.posisi, gi_trip, 0):
                logging.info("      tutup kembali %s", T.nama_bay(gi_trip, 0))
                if not await self.lapangan.kirim_perintah(gi_trip, 0, tutup=True):
                    logging.error("      command tutup %s gagal", T.nama_bay(gi_trip, 0))
                    return False
                if not await self.lapangan.tunggu_posisi(gi_trip, 0, True):
                    logging.error("      %s GAGAL menutup", T.nama_bay(gi_trip, 0))
                    return False
                await asyncio.sleep(T.T_JEDA_MANUVER)

        # --- Bagian 2: hitung ulang gardu yang masih padam ---
        data = await self.lapangan.baca()
        padam = P.gardu_padam(data.posisi, abaikan=segmen_rusak)

        if not padam:
            logging.info("      semua gardu sudah bertegangan")
            return True

        logging.info("      masih padam: %s",
                     ", ".join(T.nama_node(g) for g in padam))
        self.lapor(T.RESTORASI, padam=len(padam))

        # NOP harus masih terbuka.
        if P.tertutup(data.posisi, *T.NOP):
            logging.warning("      NOP sudah tertutup, tidak ada cadangan")
            self.catat("restorasi", "NOP sudah tertutup")
            return False

        # --- Bagian 3: cek kapasitas GI penyokong -------------------
        gi_penerima_kiri = (gi_trip != T.GI_KIRI)
        aman, total = P.kelayakan_restorasi(
            data.posisi, padam, gi_penerima_kiri
        )

        logging.info(
            "      kapasitas: %d A (batas %d A) %s",
            total,
            T.KAPASITAS_GI,
            "AMAN" if aman else "DITOLAK",
        )

        if not aman:
            logging.warning("      restorasi ditolak, melebihi kapasitas")
            self.catat("kelayakan", "ditolak, %d A melebihi batas" % total)
            return False

        # --- Bagian 4: tutup NOP setelah fault benar-benar diisolasi ---
        logging.info("      tutup %s (NOP)", T.nama_bay(*T.NOP))
        if not await self.lapangan.kirim_perintah(T.NOP[0], T.NOP[1], tutup=True):
            logging.error("      command tutup NOP gagal")
            self.catat("restorasi", "command NOP gagal")
            return False

        if not await self.lapangan.tunggu_posisi(
            T.NOP[0], T.NOP[1], True
        ):
            self.catat("restorasi", "NOP gagal menutup")
            return False

        # Posisi NOP tertutup belum cukup. Verifikasi bahwa semua gardu
        # yang seharusnya sehat benar-benar sudah mendapat jalur suplai.
        akhir = await self.lapangan.baca()
        sisa_padam = P.gardu_padam(akhir.posisi, abaikan=segmen_rusak)
        if sisa_padam:
            logging.warning(
                "      NOP tertutup tetapi masih padam: %s",
                ", ".join(T.nama_node(g) for g in sisa_padam),
            )
            self.catat(
                "restorasi",
                "masih padam: %s" % ", ".join(T.nama_node(g) for g in sisa_padam),
            )
            return False

        return True

    # ==============================================================
    # PENANGANAN LENGKAP — GANGGUAN KABEL
    # ==============================================================

    async def tangani_gangguan_kabel(self, data, gi_trip):
        """Urutan penuh untuk case 1 sampai 6."""
        mulai = time.time()
        dari_kiri = (gi_trip == T.GI_KIRI)

        # --- Proses L: cari lokasinya ------------------------------
        self.lapor(T.LOKALISASI, sasaran=0, detik=0.0)
        segmen = L.cari_segmen(data.hfd, dari_kiri)

        # Aturan L4: pola mustahil berarti ada sensor rusak.
        # Berhenti, jangan menebak.
        if segmen is None:
            logging.error("  pola HFD mustahil, kemungkinan sensor rusak")
            self.catat("lokalisasi", "pola HFD kontradiktif")
            self.lock_out = True
            self.lapor(T.LOCK_OUT)
            return False

        nama = T.nama_segmen(segmen)
        logging.warning("  LOKASI: kabel %d  (%s)", segmen + 1, nama)
        self.catat("lokalisasi", nama, "%.2f" % (time.time() - mulai))
        self.lapor(T.LOKALISASI, sasaran=segmen + 1)

        # --- Proses I: isolasi -------------------------------------
        logging.info("  ISOLASI")
        self.lapor(T.ISOLASI, detik=time.time() - mulai)

        if not await self.isolasi(data, segmen, dari_kiri):
            self.lock_out = True
            self.catat("isolasi", "gagal, lock-out")
            self.lapor(T.LOCK_OUT, detik=time.time() - mulai)
            return False

        self.catat("isolasi", nama, "%.2f" % (time.time() - mulai))

        # Setelah kedua sisi fault terbuka, lepaskan latch HFD yang aktif.
        # Kegagalan reset tidak boleh dianggap sebagai fault hilang.
        hfd_data = await self.lapangan.baca()
        reset_ok = await self.reset_hfd_aktif(hfd_data)
        if not reset_ok:
            self.catat("proteksi", "reset HFD belum bersih")

        # --- Proses R: restorasi -----------------------------------
        logging.info("  RESTORASI")
        self.lapor(T.RESTORASI, detik=time.time() - mulai)
        restorasi_ok = await self.restorasi(gi_trip, segmen)
        berhasil = restorasi_ok and reset_ok

        # --- Selesai, hitung dan laporkan --------------------------
        total = time.time() - mulai
        akhir = await self.lapangan.baca()
        self.kejadian += 1
        self.lapor(
            T.SELESAI if berhasil else T.SELESAI_SEBAGIAN,
            detik=total,
            padam=len(P.gardu_padam(akhir.posisi, abaikan=segmen)),
        )

        if berhasil:
            logging.warning("  SELESAI dalam %.2f detik", total)
            self.catat("selesai", nama, "%.2f" % total)
        else:
            logging.warning("  SELESAI SEBAGIAN dalam %.2f detik", total)
            self.catat("selesai sebagian", nama, "%.2f" % total)

        return berhasil

    # ==============================================================
    # PENANGANAN LENGKAP — GANGGUAN SUMBER
    # ==============================================================

    async def tangani_gangguan_sumber(self, data, gi_mati):
        """Tangani hilangnya salah satu sumber (case 7 dan 8)."""
        mulai = time.time()
        logging.warning("  LOKASI: hilang tegangan di %s", T.nama_node(gi_mati))
        self.catat("lokalisasi", "sumber %s hilang" % T.nama_node(gi_mati))

        sasaran = 7 if gi_mati == T.GI_KIRI else 8
        self.lapor(T.LOKALISASI, sasaran=sasaran, detik=0.0)

        kiri_hidup = (gi_mati != T.GI_KIRI)
        kanan_hidup = (gi_mati != T.GI_KANAN)
        padam = P.gardu_padam(data.posisi, kiri_hidup, kanan_hidup)

        if not padam:
            self.kejadian += 1
            total = time.time() - mulai
            self.lapor(T.SELESAI, detik=total, padam=0)
            self.catat("selesai", "gangguan sumber", "%.2f" % total)
            return True

        logging.info("      padam: %s",
                     ", ".join(T.nama_node(g) for g in padam))
        self.lapor(T.RESTORASI, padam=len(padam), detik=time.time() - mulai)

        if P.tertutup(data.posisi, *T.NOP):
            logging.warning("      NOP sudah tertutup, tidak ada cadangan")
            self.catat("restorasi", "NOP sudah tertutup")
            self.kejadian += 1
            self.lapor(T.SELESAI_SEBAGIAN, detik=time.time() - mulai)
            return False

        aman, total_arus = P.kelayakan_restorasi(
            data.posisi, padam, kiri_hidup
        )
        logging.info(
            "      kapasitas: %d A (batas %d A) %s",
            total_arus,
            T.KAPASITAS_GI,
            "AMAN" if aman else "DITOLAK",
        )

        if not aman:
            self.catat(
                "kelayakan",
                "ditolak, %d A melebihi batas" % total_arus,
            )
            self.kejadian += 1
            self.lapor(T.SELESAI_SEBAGIAN, detik=time.time() - mulai)
            return False

        logging.info("      tutup %s (NOP)", T.nama_bay(*T.NOP))
        if not await self.lapangan.kirim_perintah(
            T.NOP[0], T.NOP[1], tutup=True
        ):
            logging.error("      command tutup NOP gagal")
            self.catat("restorasi", "command NOP gagal")
            self.kejadian += 1
            self.lapor(T.SELESAI_SEBAGIAN, detik=time.time() - mulai)
            return False

        if not await self.lapangan.tunggu_posisi(T.NOP[0], T.NOP[1], True):
            logging.error("      NOP GAGAL menutup")
            self.catat("restorasi", "NOP gagal menutup")
            self.kejadian += 1
            self.lapor(T.SELESAI_SEBAGIAN, detik=time.time() - mulai)
            return False

        # Posisi switch saja belum membuktikan pemulihan beban.
        akhir = await self.lapangan.baca()
        sisa_padam = P.gardu_padam(
            akhir.posisi, kiri_hidup, kanan_hidup
        )
        total = time.time() - mulai
        berhasil = not sisa_padam

        self.kejadian += 1
        self.lapor(
            T.SELESAI if berhasil else T.SELESAI_SEBAGIAN,
            detik=total,
            padam=len(sisa_padam),
        )
        self.catat(
            "selesai" if berhasil else "selesai sebagian",
            "gangguan sumber",
            "%.2f" % total,
        )
        logging.warning(
            "  %s dalam %.2f detik",
            "SELESAI" if berhasil else "SELESAI SEBAGIAN",
            total,
        )
        return berhasil

    # ==============================================================
    # TEST / DEMO CONTROL DARI HMI
    # ==============================================================

    async def _mulai_fault_uji_kabel(self, segmen):
        """Memicu fault kabel virtual dan membuka CB sumber nyata."""
        if segmen not in T.SEGMEN:
            return False
        gi = T.GI_KIRI if segmen <= 2 else T.GI_KANAN
        if not await self.lapangan.kirim_perintah(gi, 0, tutup=False):
            self.catat("test", "gagal membuka " + T.nama_bay(gi, 0))
            return False
        if not await self.lapangan.tunggu_posisi(gi, 0, False):
            self.catat("test", "CB sumber gagal terbuka")
            return False
        self.uji_fault_segmen = segmen
        self.catat("test", "fault kabel " + T.nama_segmen(segmen))
        return True

    async def _mulai_fault_uji_sumber(self, gi):
        """Memicu fault sumber: CB GI yang fault HARUS OPEN.

        Setelah CB sumber dibuka, controller tetap membawa state
        ``uji_fault_sumber`` sehingga siklus utama mengenali kejadian ini
        sebagai gangguan sumber, bukan sebagai gangguan kabel. NOP kemudian
        dapat ditutup oleh proses restorasi untuk memindahkan suplai ke GI
        yang sehat.
        """
        if gi not in (T.GI_KIRI, T.GI_KANAN):
            return False

        # Untuk simulasi fault sumber, CB sumber yang fault wajib OPEN.
        if not await self.lapangan.kirim_perintah(gi, 0, tutup=False):
            self.catat("test", "gagal membuka " + T.nama_bay(gi, 0))
            return False
        if not await self.lapangan.tunggu_posisi(gi, 0, False):
            self.catat("test", "CB sumber gagal terbuka " + T.nama_node(gi))
            return False

        self.uji_fault_sumber = gi
        self.catat("test", "fault sumber " + T.nama_node(gi) + " -> CB OPEN")
        return True

    def _terapkan_overlay_uji(self, data):
        """Tambahkan sinyal fault virtual sesudah snapshot RTU dibaca."""
        segmen = self.uji_fault_segmen
        if segmen is not None:
            gi = T.GI_KIRI if segmen <= 2 else T.GI_KANAN
            data.trip[gi] = 1
            dari_kiri = gi == T.GI_KIRI
            if segmen > 0:
                urutan = range(0, segmen + 1) if dari_kiri else range(5, segmen - 1, -1)
                for s in urutan:
                    kiri, kanan = T.bay_pengapit(s)
                    node, bay = kiri if dari_kiri else kanan
                    if not T.adalah_gardu_induk(node):
                        data.hfd[(node, bay)] = 1

        gi = self.uji_fault_sumber
        if gi is not None:
            data.under_voltage[gi] = 1

    async def _repair_uji(self):
        """TEST ONLY: cepat mengembalikan simulator ke kondisi launch.

        Urutannya sengaja: RESET PROTEKSI -> COMMAND TOPOLOGI ->
        VERIFIKASI. Pada versi lama, CB GI diperintah CLOSE saat latch
        trip masih aktif, lalu baru di-reset. Akibatnya perintah CLOSE
        selesai tetapi CB tetap OPEN.
        """
        ok = True

        # 1) Bersihkan semua latch proteksi terlebih dahulu.
        reset_results = await asyncio.gather(
            *(self.lapangan.kirim_reset(node) for node in range(len(T.NODE))),
            return_exceptions=True,
        )
        if not all(result is True for result in reset_results):
            ok = False
            self.catat("test", "sebagian reset proteksi gagal")

        # Beri kesempatan task RTU memproses reset coil sebelum CB/LBS
        # diberi command CLOSE/OPEN.
        await asyncio.sleep(0.15)

        # 2) Kirim semua command posisi target tanpa menunggu satu per satu.
        #    Ini jauh lebih cepat daripada 12x timeout konfirmasi berurutan.
        async def command_node(node):
            hasil = []
            for bay in range(T.jumlah_bay(node)):
                target = (node, bay) != T.NOP
                hasil.append(
                    await self.lapangan.kirim_perintah(
                        node, bay, tutup=target
                    )
                )
            return all(hasil)

        command_results = await asyncio.gather(
            *(command_node(node) for node in range(len(T.NODE))),
            return_exceptions=True,
        )
        if not all(result is True for result in command_results):
            ok = False

        # 3) Verifikasi satu snapshot penuh sampai seluruh 12 posisi cocok.
        target_positions = {
            (node, bay): ((node, bay) != T.NOP)
            for node in range(len(T.NODE))
            for bay in range(T.jumlah_bay(node))
        }

        deadline = time.monotonic() + 3.0
        normal = False
        while time.monotonic() < deadline:
            data = await self.lapangan.baca()
            normal = (
                data.semua_online()
                and all(
                    data.posisi.get(key) == target
                    for key, target in target_positions.items()
                )
            )
            if normal:
                break
            await asyncio.sleep(0.05)

        if not normal:
            ok = False
            self.catat("test", "konfigurasi normal gagal dikonfirmasi")

        # 4) Bersihkan state test/controller.
        self.uji_fault_segmen = None
        self.uji_fault_sumber = None
        self.lock_out = False
        self.siaga = False
        self.tulis_hr(T.HR_TEST_REPAIR, 0)
        self.tulis_hr(T.HR_TEST_SOURCE, 0)
        for reg in range(T.HR_FAULT_BASE, T.HR_FAULT_BASE + 6):
            self.tulis_hr(reg, 0)
        self.catat(
            "test",
            "repair dan konfigurasi normal",
        )
        return ok

    async def _proses_command_test(self):
        hr = self.baca_hr(0, T.JUMLAH_HR_CONTROLLER)

        if hr[T.HR_TEST_REPAIR]:
            await self._repair_uji()
            return

        if self.uji_fault_segmen is not None or self.uji_fault_sumber is not None:
            return

        requested_segments = [i for i in range(6) if hr[T.HR_FAULT_BASE + i]]
        if requested_segments:
            segmen = requested_segments[0]
            for i in requested_segments:
                self.tulis_hr(T.HR_FAULT_BASE + i, 0)
            if self.siaga:
                await self._mulai_fault_uji_kabel(segmen)
            else:
                self.catat("test", "fault kabel ditolak: SHG belum siaga")
            return

        source_cmd = hr[T.HR_TEST_SOURCE]
        if source_cmd in (1, 2):
            self.tulis_hr(T.HR_TEST_SOURCE, 0)
            if self.siaga:
                gi = T.GI_KIRI if source_cmd == 1 else T.GI_KANAN
                await self._mulai_fault_uji_sumber(gi)
            else:
                self.catat("test", "fault sumber ditolak: SHG belum siaga")

    # ==============================================================
    # SATU SIKLUS — dijalankan tiap satu detik
    # ==============================================================

    async def siklus(self):
        # Proses command TEST dari HMI sebelum mengambil snapshot.
        await self._proses_command_test()

        # Langkah pertama selalu sama: ambil potret lapangan.
        data = await self.lapangan.baca()
        self._terapkan_overlay_uji(data)

        # Terbitkan status online dan konfigurasi apa pun keadaannya,
        # supaya HMI tetap punya informasi walau ada RTU yang mati.
        self.terbitkan_online(data)

        # --- Penjaga 1: semua RTU harus menjawab -------------------
        if not data.semua_online():
            self.terbitkan_shg(False, False, False)
            self.lapor(T.MENUNGGU_RTU)
            return

        # --- Operator boleh melepas lock-out lewat coil 1 ----------
        if self.baca_coil(T.CO_RESET_LOCK_OUT):
            if self.lock_out:
                logging.warning("Lock-out dilepas operator")
            self.lock_out = False
            self.tulis_coil(T.CO_RESET_LOCK_OUT, 0)  # tombol sekali tekan

        # --- Penjaga 2: operator mengizinkan? ----------------------
        if not self.baca_coil(T.CO_SHG_ENABLE):
            self.terbitkan_shg(False, False, False)
            self.lapor(T.DISABLE)
            return

        # --- Penjaga 3: sedang lock-out? ---------------------------
        if self.lock_out:
            self.terbitkan_shg(False, False, True)
            self.lapor(T.LOCK_OUT)
            return

        # --- Cari pemicu -------------------------------------------
        # Aturan D2: pemicu = CB TERBUKA  ATAU  under voltage.
        # Perhatikan syarat posisi CB-nya berlawanan di dua baris ini.
        # Itulah yang membedakan gangguan kabel dari gangguan sumber.
        gi_trip = None
        gi_mati = None

        # Source-fault test: CB memang sengaja dibuka oleh HMI/testbench,
        # jadi jangan menunggu syarat "UV + CB closed". State uji ini adalah
        # trigger eksplisit untuk proses gangguan sumber.
        if self.uji_fault_sumber in (T.GI_KIRI, T.GI_KANAN):
            gi_mati = self.uji_fault_sumber
        else:
            for gi in (T.GI_KIRI, T.GI_KANAN):
                cb_tertutup = P.tertutup(data.posisi, gi, 0)
                if data.trip.get(gi) and not cb_tertutup:
                    gi_trip = gi          # kabel rusak, CB sudah membuka
                    break
                if data.under_voltage.get(gi) and cb_tertutup:
                    gi_mati = gi          # sumber hilang, CB masih menutup
                    break

        # --- Tidak ada pemicu: perbarui kesiagaan ------------------
        if gi_trip is None and gi_mati is None:
            siap = P.kondisi_awal_terpenuhi(
                data.posisi, data.hfd, data.under_voltage, len(data.online)
            )
            if siap != self.siaga:
                logging.info("SHG %s", "SIAGA" if siap else "tidak siaga")
            self.siaga = siap
            self.terbitkan_shg(siap, False, False)

            # Biarkan fase SELESAI bertahan sebentar supaya HMI sempat
            # menampilkannya sebelum kembali ke siaga.
            if self.fase not in (T.SELESAI, T.SELESAI_SEBAGIAN) or siap:
                self.lapor(T.SIAGA if siap else T.BELUM_SIAGA,
                           padam=len(P.gardu_padam(data.posisi)))
            return

        # --- Ada pemicu --------------------------------------------
        # Aturan D4, dan ini bagian paling halus di seluruh program.
        #
        # Yang diperiksa adalah self.siaga — nilai yang DIKUNCI di
        # siklus tenang terakhir, bukan keadaan sekarang.
        #
        # Kenapa: begitu CB terbuka, kondisi awal otomatis rusak.
        # Kalau diperiksa sekarang, jawabannya SELALU "tidak siaga",
        # dan FLISR tidak akan pernah bekerja sama sekali.
        if not self.siaga:
            logging.info("Gangguan terdeteksi tapi SHG tidak siaga")
            self.terbitkan_shg(False, False, False)
            self.lapor(T.BELUM_SIAGA)
            return

        # --- Ambil alih --------------------------------------------
        # Setelah trigger muncul, kondisi jaringan sudah tidak normal.
        # Kunci kesiagaan false agar kejadian yang sama tidak dieksekusi
        # berulang-ulang pada siklus polling berikutnya.
        self.siaga = False
        mulai_penanganan = time.monotonic()
        self.terbitkan_shg(True, True, False)   # in progress = SET
        try:
            if gi_trip is not None:
                logging.warning("PEMICU: %s trip. FLISR mengambil alih.",
                                T.nama_node(gi_trip))
                selesai = await asyncio.wait_for(
                    self.tangani_gangguan_kabel(data, gi_trip),
                    T.T_SHG_TIMEOUT,
                )
            else:
                logging.warning("PEMICU: %s hilang tegangan. FLISR mengambil alih.",
                                T.nama_node(gi_mati))
                selesai = await asyncio.wait_for(
                    self.tangani_gangguan_sumber(data, gi_mati),
                    T.T_SHG_TIMEOUT,
                )
            # in progress kembali RESET, incomplete diisi hasilnya.
            self.terbitkan_shg(True, False, not selesai)
            self.uji_fault_segmen = None
            self.uji_fault_sumber = None

        except asyncio.TimeoutError:
            # Aturan X2: lewat 30 detik, hentikan dan laporkan.
            logging.error("TIMEOUT %.0f detik terlampaui", T.T_SHG_TIMEOUT)
            self.catat("timeout", "SHG incomplete")
            self.terbitkan_shg(True, False, True)
            self.kejadian += 1
            self.lapor(T.SELESAI_SEBAGIAN, detik=T.T_SHG_TIMEOUT)
            self.siaga = False
            self.uji_fault_segmen = None
            self.uji_fault_sumber = None

        except Exception as e:
            # Error internal saat manuver tidak boleh membuat HMI terus
            # melihat status in-progress seolah-olah proses masih jalan.
            logging.exception("SHG berhenti karena kesalahan internal: %s", e)
            self.catat("kesalahan", "SHG exception: %s" % e)
            self.terbitkan_shg(True, False, True)
            self.kejadian += 1
            self.lapor(
                T.SELESAI_SEBAGIAN,
                detik=time.monotonic() - mulai_penanganan,
            )
            self.siaga = False
            self.uji_fault_segmen = None
            self.uji_fault_sumber = None

    # ==============================================================
    # PERULANGAN UTAMA
    # ==============================================================

    async def loop(self):
        await self.lapangan.sambung()
        logging.info("Controller FLISR siap. Status SHG dilayani di port %d",
                     T.PORT_SHG)

        while True:
            await asyncio.sleep(T.T_POLL)
            try:
                await self.siklus()
            except Exception as e:
                # Satu kesalahan tidak boleh mematikan controller.
                # Catat, lalu lanjut ke siklus berikutnya.
                logging.error("kesalahan siklus: %s", e)


async def jalankan():
    ctrl = Controller()

    # create_task menjalankan loop algoritma di latar belakang.
    asyncio.create_task(ctrl.loop())

    # StartAsyncTcpServer memblokir selamanya, melayani HMI.
    # Dua-duanya hidup bersamaan di satu proses.
    await StartAsyncTcpServer(
        context=ctrl.context, address=("0.0.0.0", T.PORT_SHG)
    )


if __name__ == "__main__":
    try:
        asyncio.run(jalankan())
    except KeyboardInterrupt:
        pass   # Ctrl+C tidak perlu memuntahkan jejak kesalahan
