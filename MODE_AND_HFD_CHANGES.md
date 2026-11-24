# Catatan revisi controller dua mode dan fault-case HFD

## Routing yang aktif

- `controller_rtu.py` berjalan pada mode Y dan menggunakan gateway HUe `192.168.250.1:502`, CHFLISR logical Unit IDs 1..7.
- `lapangan_hue.py` mencoba membaca FC01 status (GI 6 point, GD 10 point); jika CHFLISR menolak FC01, adapter mencoba FC02. Setelah selector Remote terkonfirmasi, adapter mengirim pulse FC05 ke source point yang tercantum pada CoreDb Command.
- `controller.py` berjalan pada mode N dan mengakses simulator RTU langsung melalui alamat `.3`–`.9`, Unit ID 1. Field status juga dibaca lewat FC01.
- HUe downstream Unit IDs mengikuti konfigurasi EBC: GIA=1, GD01=2, GD02=2, GD03=3, GD04=4, GD05=2, GIB=3.
- `rtu_gi.py` dan `rtu_gd.py` menyajikan datastore yang sama di Unit ID 1 dan alias MDBM masing-masing. Command EBC diterjemahkan menjadi event tanpa menimpa status FC01.

## CoreDb Command yang tersedia dan yang belum tersedia

Perintah switch yang tersedia: GI CS1=CLOSE/CS2=OPEN; GD LBS1 CS1=CLOSE/CS2=OPEN; GD LBS2 CS6=CLOSE/CS7=OPEN. Reset GD HFD hanya memiliki destination CS0/CS5 tanpa SOURCE_COORD, dan tidak ada command GI trip reset. Software mengembalikan gagal bila reset latch aktif tetapi source EBC belum tersedia. Source tambahan yang diusulkan tercatat di `EBC_CS_MAPPING.md`; file EBC/XLS input tidak diubah.

## Perbaikan testbench

- System Behavior membaca balik FC01 langsung dari simulator dan memeriksa HFD pada CS0/CS5, bukan pada indeks switch.
- Testbench `.250.2:503` mempertahankan Unit ID 1 dan menambahkan Unit ID 30 yang digunakan oleh EBC M30_TestBench.
- EBC testbench status FC01 CS0..7 menandai K1..K8 setelah hasil case terverifikasi.
- CO10/CO11/CO12 menjadi command internal simulator untuk mode direct/testbench, terpisah dari status FC01 CS0..CS9.

## Perintah validasi

```powershell
py validate_ebc_cs_mapping.py
py validate_routing_config.py
py validate_hfd_cases.py
# Start seven RTU simulators, then:
py validate_multi_master.py
```

## Batas pengujian

Syntax compile dan static checks dilakukan pada ZIP yang diedit. Runtime integration dan komunikasi fisik HUe tidak dapat diverifikasi dari workspace ini karena dependensi `pymodbus`/`streamlit` tidak tersedia dan tidak ada koneksi ke perangkat HUe. Uji di lab tetap diperlukan.
