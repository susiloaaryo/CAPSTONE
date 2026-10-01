"""LANGKAH 2 — Penalaran topologi bebas-Modbus."""

import topologi as T


def tertutup(posisi, node, bay):
    """True hanya jika posisi saklar sudah terkonfirmasi tertutup."""
    return posisi.get((node, bay), False)


def segmen_terhubung(posisi, segmen, abaikan=None):
    """True jika kedua saklar pengapit kabel tertutup."""
    if segmen == abaikan:
        return False
    kiri, kanan = T.bay_pengapit(segmen)
    return tertutup(posisi, *kiri) and tertutup(posisi, *kanan)


def gardu_tersuplai(posisi, dari_kiri, gi_hidup=True, abaikan=None):
    """Daftar GD yang masih mendapat suplai dari satu GI."""
    if not gi_hidup:
        return []

    if dari_kiri:
        node, bay = T.GI_KIRI, 0
        urutan = range(6)
    else:
        node, bay = T.GI_KANAN, 0
        urutan = range(5, -1, -1)

    if not tertutup(posisi, node, bay):
        return []

    hasil = []
    for segmen in urutan:
        if not segmen_terhubung(posisi, segmen, abaikan):
            break

        berikut = segmen + 1 if dari_kiri else segmen
        if berikut in (T.GI_KIRI, T.GI_KANAN):
            break

        hasil.append(berikut)
        node = berikut
        bay = 1 if dari_kiri else 0

        if not tertutup(posisi, node, bay):
            break

    return hasil


def gardu_padam(posisi, gi_kiri_hidup=True, gi_kanan_hidup=True, abaikan=None):
    """Daftar GD yang tidak tersuplai dari sisi mana pun."""
    hidup = set(gardu_tersuplai(posisi, True, gi_kiri_hidup, abaikan))
    hidup |= set(gardu_tersuplai(posisi, False, gi_kanan_hidup, abaikan))
    return [g for g in T.GARDU if g not in hidup]


def konfigurasi_normal(posisi):
    """Semua saklar tertutup kecuali NOP terbuka."""
    for node in range(len(T.NODE)):
        for bay in range(T.jumlah_bay(node)):
            harus_tutup = (node, bay) != T.NOP
            if tertutup(posisi, node, bay) != harus_tutup:
                return False
    return True


def kondisi_awal_terpenuhi(posisi, hfd, under_voltage, jumlah_online):
    """Syarat kesiagaan SHG.

    1. Semua RTU online.
    2. Semua saklar pada konfigurasi normal.
    3. Tidak ada HFD aktif.
    4. Tidak ada under-voltage.

    Over-voltage tetap dibaca dan dilaporkan oleh controller, tetapi
    ambang alarm OV tidak ditentukan di berkas sumber ini, sehingga
    tidak ditebak menjadi syarat baru di sini.
    """
    if jumlah_online < len(T.NODE):
        return False
    if not konfigurasi_normal(posisi):
        return False
    if any(hfd.values()):
        return False
    if any(under_voltage.values()):
        return False
    return True


def kelayakan_restorasi(posisi, gardu_yang_padam, gi_penerima_kiri):
    """Uji kapasitas GI penyokong setelah gardu padam dipindahkan."""
    beban_sekarang = sum(
        T.BEBAN[g] for g in gardu_tersuplai(posisi, gi_penerima_kiri)
    )
    tambahan = sum(T.BEBAN[g] for g in gardu_yang_padam)
    total = beban_sekarang + tambahan
    return total <= T.KAPASITAS_GI, total
