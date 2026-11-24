# NEWEST.ebc — CoreDb CS dan Modbus FC01/FC05

Dokumen ini merangkum konfigurasi aktual dari file `NEWEST(1).ebc` dan workbook CoreDB yang diberikan untuk proyek ini. Yang dinyatakan eksplisit oleh EBC adalah polling MDBM **HUe → RTU** menggunakan FC01, start address `0`, interval `1000 ms`. Berkas MDBE server `CHFLISR` hanya menyatakan protokol TCP dan Unit ID. Namun workbook CoreDb memetakan seluruh status perangkat ke koordinat `CS:0..5` (GI) dan `CS:0..9` (GD). Menurut *Modbus Devices – User Manual* Schneider, profil Modbus Slave STD membaca koordinat `CS` dengan FC01; FC02 digunakan untuk koordinat `IS`. Karena itu controller Mode Y harus membaca FC01. FC02 bukan fallback yang setara untuk image `CS` ini.

## 1. Status point image

| Perangkat | CS / FC01 | Makna |
|---|---:|---|
| GI A / GI B | 0 | CBTR / trip |
| GI A / GI B | 1 | CB CLOSE |
| GI A / GI B | 2 | CB OPEN |
| GI A / GI B | 3 | CB LOCAL |
| GI A / GI B | 4 | CB REMOTE |
| GI A / GI B | 5 | UV |
| GD01–GD05 | 0 | LBS1 HFD |
| GD01–GD05 | 1 | LBS1 CLOSE |
| GD01–GD05 | 2 | LBS1 OPEN |
| GD01–GD05 | 3 | LBS1 LOCAL |
| GD01–GD05 | 4 | LBS1 REMOTE |
| GD01–GD05 | 5 | LBS2 HFD |
| GD01–GD05 | 6 | LBS2 CLOSE |
| GD01–GD05 | 7 | LBS2 OPEN |
| GD01–GD05 | 8 | LBS2 LOCAL |
| GD01–GD05 | 9 | LBS2 REMOTE |

Urutan ini sama dengan `CS:0..5` untuk GI dan `CS:0..9` untuk GD pada CoreDB Status. GD UV/OV tidak masuk ke image CoreDB yang diberikan. HUe mengambil image lapangan ini melalui FC01 sesuai konfigurasi MDBM. Untuk sisi controller → CHFLISR, adapter membaca koordinat `CS` melalui FC01 sesuai pemetaan Modbus Slave STD. Controller lokal tetap mengekspos agregatnya ke HMI/PLC melalui FC02 pada server controller `.250.2:502`.

## 2. Dua lapis Unit ID (jangan disamakan)

**CHFLISR server Unit ID** dipakai `controller_rtu.py` saat mengakses HUe `.250.1:502`:

| Unit ID CHFLISR | Logical server bin | Perangkat |
|---:|---|---|
| 1 | S1_GIA | GI SATU |
| 2 | S2_GD1 | GD01 |
| 3 | S3_GD2 | GD02 |
| 4 | S4_GD3 | GD03 |
| 5 | S5_GD4 | GD04 |
| 6 | S6_GD5 | GD05 |
| 7 | S7_GIB | GI DUA |

**Downstream MDBM Unit ID** dipakai HUe ketika mempoll server Modbus TCP RTU di laptop:

| RTU | IP | Downstream Unit ID |
|---|---|---:|
| GI SATU / M1_GIA | `192.168.250.3` | 1 |
| GD01 / M2_GD1 | `192.168.250.9` | 2 |
| GD02 / M3_GD2 | `192.168.250.5` | 2 |
| GD03 / M4_GD3 | `192.168.250.6` | 3 |
| GD04 / M5_GD4 | `192.168.250.7` | 4 |
| GD05 / M6_GD5 | `192.168.250.8` | 2 |
| GI DUA / M7_GIB | `192.168.250.4` | 3 |

Karena itu simulator mengaktifkan Unit ID 1 (mode direct/testbench) **dan** alias downstream yang diperlukan untuk masing-masing RTU. CHFLISR IDs tetap 1..7 di sisi HUe, tetapi bukan berarti setiap RTU downstream memakai Unit ID yang sama.

## 3. Switch commands yang memang ada di CoreDB Command

Setiap perintah OPEN dan CLOSE adalah point terpisah. Controller mengirim pulse FC05 ke source coordinate pada `Sx_*`; CoreDB mengarahkan command tersebut ke coordinate `Mx_*`:

| Perangkat | CLOSE source | OPEN source | Destination |
|---|---:|---:|---|
| GI SATU (S1_GIA) | CS:1 | CS:2 | M1_GIA CS:1 / CS:2 |
| GD01 (S2_GD1) LBS1 | CS:1 | CS:2 | M2_GD1 CS:1 / CS:2 |
| GD01 (S2_GD1) LBS2 | CS:6 | CS:7 | M2_GD1 CS:6 / CS:7 |
| GD02 (S3_GD2) LBS1/LBS2 | CS:1 / CS:6 | CS:2 / CS:7 | M3_GD2 same CS |
| GD03 (S4_GD3) LBS1/LBS2 | CS:1 / CS:6 | CS:2 / CS:7 | M4_GD3 same CS |
| GD04 (S5_GD4) LBS1/LBS2 | CS:1 / CS:6 | CS:2 / CS:7 | M5_GD4 same CS |
| GD05 (S6_GD5) LBS1/LBS2 | CS:1 / CS:6 | CS:2 / CS:7 | M6_GD5 same CS |
| GI DUA (S7_GIB) | CS:1 | CS:2 | M7_GIB CS:1 / CS:2 |

The software sends `True` then `False` (a 1.2-second momentary pulse) to these mapped source points via FC05. The RTU simulator consumes incoming FC05 command writes as events and keeps its FC01 status image intact. It does not treat those EBC switch coils as persistent direct-mode level commands; direct-mode command registers are simulator-only CO10/CO11/CO12.

## 4. Reset mapping gap in the provided CoreDB

The supplied Command table has ten HFD reset entries with **DEST_COORD only**:

- GD1..GD5 LBS1 reset -> M2..M6 `CS:0`;
- GD1..GD5 LBS2 reset -> M2..M6 `CS:5`.

Those ten rows have no `SOURCE_COORD`. The same table also has no GI trip-reset row. Therefore a controller connected only to CHFLISR cannot initiate those reset commands using a source coil that the supplied mapping actually defines.

The ZIP software documents these additional source coordinates as a proposed EBC change (not present in the supplied EBC/workbook). The controller does not write them while `HUE_RESET_SOURCE_MAP_AVAILABLE = False`:

- `S1_GIA` and `S7_GIB` `CS:6` -> `M1_GIA` / `M7_GIB` `CS:0` (GI trip reset);
- `S2_GD1`..`S6_GD5` `CS:10` -> `M2`..`M6` `CS:0` (HFD1 reset);
- `S2_GD1`..`S6_GD5` `CS:11` -> `M2`..`M6` `CS:5` (HFD2 reset).

Until those source mappings are explicitly added, downloaded to HUe, and verified, the controller will return `False` when an active trip/HFD needs reset without writing to those unconfigured addresses, and FLISR may finish as **SELESAI SEBAGIAN**. Only then should `HUE_RESET_SOURCE_MAP_AVAILABLE` be changed to `True` in `topologi.py`. This is deliberate: the software must not report successful protection reset without a confirmed FC01 clear. No change to the supplied `.ebc` or `.xlsx` was made.

## 5. Testbench channel

The EBC MDBM config also polls `M30_TestBench` at `192.168.250.2:503`, Unit ID `30`, FC01 start `0`, quantity `10`. `system_behavior.py` now serves Unit ID 30 (and retains Unit ID 1 for local HMI clients) and publishes case flags on CS0..CS7: K1..K6 at bits 0..5, K7 at bit 6, K8 at bit 7.

## 6. Validation

Run these from the project folder after installing `requirements.txt`:

```powershell
py validate_ebc_cs_mapping.py
py validate_routing_config.py
py validate_command_events.py
py validate_multi_master.py
py validate_hfd_cases.py
```

`validate_multi_master.py` requires all seven simulator RTU processes to be running. These scripts do not emulate or certify the physical HUe; confirm the live channel configuration and command handling in Easergy Builder before any switching test.


## 7. Troubleshooting: TCP connected, tetapi FC01 tidak mendapat response

Jika log menunjukkan `terkoneksi ke HUe` lalu `No response received`, TCP handshake berhasil tetapi layanan MDBE belum memberikan balasan Modbus. Unit ID CHFLISR 1..7 sudah sesuai bin MDBE `S1_GIA`..`S7_GIB`; jangan mengganti Unit ID berdasarkan gejala ini.

1. Jalankan `py diagnose_hue_gateway.py` dari folder project. Script ini hanya membaca FC01 (tidak menulis command) dan membuka koneksi baru untuk setiap Unit ID.
2. Pastikan IP sumber laptop di NIC yang menuju MNT adalah `192.168.250.2/24`, karena `CHFLISR` membatasi remote peer ke `192.168.250.2`.
3. Di Easergy Builder, pastikan CHFLISR berada pada mode CALLED, local IP `192.168.250.1`, local port `502`, dan setiap device MDBE `S1_GIA`..`S7_GIB` memakai channel CHFLISR dengan slave number 1..7 serta profil STD.
4. Pastikan konfigurasi terbaru benar-benar sudah dikirim ke HUe dan modul Modbus Slave aktif. Workbook tidak memetakan `MDBE_COM_ENABLED`; menurut manual, jika koordinat opsional itu tidak dipetakan, MDBE akan selalu menjawab request.
5. Ulangi tes baca dengan Unit ID 1, FC01, address 0, quantity 6. Jika masih `No response`, masalah ada pada layanan/configuration MDBE, remote access/channel, atau konfigurasi yang sedang aktif di HUe—bukan pada logika FLISR atau urutan bit CS.

Adapter sekarang membuat ulang koneksi setelah transport timeout agar kegagalan satu Unit ID tidak menyebabkan semua pembacaan berikutnya gagal sebagai `Not connected`.
