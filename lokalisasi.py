"""LANGKAH 3 — Mencari segmen yang rusak dari pola HFD."""

import topologi as T


def cari_segmen(hfd, dari_kiri):
    """Tentukan kabel yang rusak berdasarkan pola HFD dari sumber.

    True  -> telusur GI SATU -> GI DUA.
    False -> telusur GI DUA -> GI SATU.

    Mengembalikan nomor segmen 0..5 atau None jika pola tidak mungkin.
    """
    urutan = range(6) if dari_kiri else range(5, -1, -1)
    terakhir_nyala = None
    sudah_ketemu_padam = False

    for segmen in urutan:
        kiri, kanan = T.bay_pengapit(segmen)
        node, bay = kiri if dari_kiri else kanan

        # Hanya GD yang memiliki HFD.
        if T.adalah_gardu_induk(node):
            continue

        aktif = bool(hfd.get((node, bay), 0))

        if aktif:
            if terakhir_nyala is not None and sudah_ketemu_padam:
                # Pola 1 -> 0 -> 1 tidak konsisten dengan penelusuran
                # gangguan satu arah.
                return None
            terakhir_nyala = segmen
        elif terakhir_nyala is not None:
            sudah_ketemu_padam = True

    if terakhir_nyala is not None:
        return terakhir_nyala

    # Tidak ada sensor HFD yang aktif: fault diasumsikan berada pada
    # segmen pertama dari sumber yang trip.
    return 0 if dari_kiri else 5
