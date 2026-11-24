# Panduan Pelaksanaan Demo D-LUMEN pada 10 Perangkat Fisik

> **Arsip arsitektur lama.** Gunakan `README.md` dan `docs/REFACTOR_MASTER_WORKER.md`
> untuk Master terpusat. Instruksi PostgreSQL atau GeoTIFF pada Worker di dokumen ini tidak berlaku lagi.

Panduan ini digunakan oleh Sandria, Kenanga, Fawwaz, dan pemilik perangkat tambahan untuk menyiapkan serta menjalankan demo D-LUMEN. Target minimal adalah satu komputer Master dan sembilan komputer Worker yang terhubung ke jaringan yang sama. Semua pengujian harus memakai data nyata dan hasil yang ditampilkan harus sesuai kondisi sistem.

## 1. Susunan Sistem

```text
                         MASTER
                  MacBook Sandria :5050
        Dashboard, scheduler, heartbeat, result aggregator
                            |
                    Wi-Fi / LAN yang sama
                            |
  WORKER-01  WORKER-02  WORKER-03 ... WORKER-09 atau lebih
  PostgreSQL + VIIRS + ProcessPoolExecutor minimal 2 proses
```

Master membuat task berdasarkan bulan, mendistribusikannya kepada Worker, memantau heartbeat, dan menggabungkan hasil. Worker mengambil task sesuai kapasitas proses, mengolah PostgreSQL atau GeoTIFF VIIRS, lalu mengirimkan hasil kepada Master.

## 2. Pembagian Tanggung Jawab

| Anggota | Tanggung jawab |
|---|---|
| Sandria | Menjalankan Master, dashboard, query, benchmark, dan menyimpan hasil |
| Kenanga | Memeriksa serta menjalankan WORKER-01 sampai WORKER-05 |
| Fawwaz | Memeriksa WORKER-06 sampai WORKER-09, merekam bukti, dan melakukan simulasi kegagalan |

Jika tersedia lebih dari sembilan Worker, perangkat tambahan menjadi cadangan atau digunakan untuk eksperimen tambahan setelah pengujian wajib selesai.

## 3. Persiapan Sebelum Hari Demo

Setiap komputer harus memiliki:

- Source code D-LUMEN dengan versi yang sama.
- Python 3.11 atau lebih baru.
- Virtual environment dan dependency proyek.
- Dataset VIIRS sesuai metadata partisinya.
- PostgreSQL dan tabel `viirs_monthly` bila menjalankan operasi database.
- File `.env` lokal yang tidak dibagikan ke repository.
- Ruang penyimpanan dan daya baterai yang cukup.

### 3.1 Instalasi macOS atau Linux

```bash
chmod +x scripts/*.sh
./scripts/setup_node.sh
```

### 3.2 Instalasi Windows

Buka PowerShell di direktori D-LUMEN:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
powershell -ExecutionPolicy Bypass -File scripts/setup_node.ps1
```

Keluaran yang diharapkan:

```text
SETUP OK
```

## 4. Strategi Penempatan Data

### Pilihan yang disarankan untuk demo

Salin dataset 2020–2025 lengkap ke seluruh Worker. Isi konfigurasi:

```env
DLUMEN_PARTITIONS=2020,2021,2022,2023,2024,2025
```

Strategi ini memudahkan pengujian 1, 2, 4, 6, dan 9 Worker serta memungkinkan task dipindahkan ketika satu Worker gagal.

### Pilihan jika dataset tidak dapat disalin penuh

| Worker | Partisi |
|---|---|
| WORKER-01, WORKER-02, WORKER-03 | 2020, 2021 |
| WORKER-04, WORKER-05, WORKER-06 | 2022, 2023 |
| WORKER-07, WORKER-08, WORKER-09 | 2024, 2025 |

Setiap partisi mempunyai tiga replika. Replika tidak menyebabkan double counting karena Master hanya membuat satu task untuk setiap partisi. Pengujian scalability dengan jumlah Worker terbatas harus tetap memilih kombinasi Worker yang mencakup semua partisi workload.

## 5. Konfigurasi Master

File `.env` pada MacBook Sandria:

```env
DLUMEN_TOKEN=GANTI_DENGAN_TOKEN_DEMO_YANG_SAMA
DLUMEN_MASTER_PORT=5050
DLUMEN_DISCOVERY_PORT=5005
DLUMEN_DB_NAME=dlumen_db
DLUMEN_DB_USER=sandrianuriya
DLUMEN_DB_HOST=/tmp
DLUMEN_DB_PORT=5432
DLUMEN_MAX_RETRIES=2
DLUMEN_TASK_TIMEOUT=120
DLUMEN_HEARTBEAT_TIMEOUT=15
```

Jangan memasukkan `.env` ke ZIP source atau repository.

Setelah tersambung ke jaringan demo, cari alamat IP Master:

```bash
ipconfig getifaddr en0
```

Jika hasilnya `192.168.1.20`, dashboard dapat diakses perangkat lain melalui:

```text
http://192.168.1.20:5050
```

## 6. Konfigurasi Worker

Contoh `.env` WORKER-01:

```env
DLUMEN_TOKEN=GANTI_DENGAN_TOKEN_DEMO_YANG_SAMA
DLUMEN_MASTER_URL=http://192.168.1.20:5050
DLUMEN_WORKER_ID=WORKER-01
DLUMEN_WORKER_PORT=5002
DLUMEN_PROCESSES=2
DLUMEN_PARTITIONS=2020,2021,2022,2023,2024,2025
DLUMEN_DATA_DIR=data/raw
DLUMEN_DB_NAME=dlumen_db
DLUMEN_DB_USER=postgres
DLUMEN_DB_HOST=127.0.0.1
DLUMEN_DB_PORT=5432
DLUMEN_DB_PASSWORD=PASSWORD_POSTGRES_LOKAL
```

Setiap komputer mengganti `DLUMEN_WORKER_ID` menjadi ID unik dari `WORKER-01` sampai `WORKER-09`. Port 5002 boleh sama karena digunakan pada komputer fisik berbeda. Jika dua Worker dijalankan pada komputer yang sama hanya untuk troubleshooting, gunakan port berbeda, tetapi keduanya tetap dihitung sebagai satu node fisik.

Jika PostgreSQL Windows memakai port 5433, ubah:

```env
DLUMEN_DB_PORT=5433
```

## 7. Persiapan PostgreSQL Worker

Pastikan database `dlumen_db` sudah dibuat. Kemudian jalankan:

```bash
python -m database.init_db
python -m database.import_viirs
```

Kedua perintah aman dijalankan ulang dan tidak menghapus data lama.

Periksa data:

```sql
SELECT year, COUNT(*)
FROM viirs_monthly
GROUP BY year
ORDER BY year;
```

Jumlah bulan harus sesuai dengan partisi yang diiklankan Worker.

## 8. Pemeriksaan Kesiapan

### Master

```bash
python scripts/check_readiness.py --role master
```

### Worker

```bash
python scripts/check_readiness.py --role worker
```

Jangan memakai perangkat sebagai Worker sebelum pemeriksaan dependency, GeoTIFF, multiprocessing, PostgreSQL, dan data menunjukkan `OK`.

## 9. Pemeriksaan Jaringan

Semua perangkat harus terhubung ke Wi-Fi, hotspot, atau LAN yang sama. Dari browser setiap Worker, buka:

```text
http://IP-MASTER:5050/health
```

Keluaran yang diharapkan:

```json
{
  "role": "master",
  "status": "online"
}
```

Jika tidak dapat dibuka:

1. Periksa kembali IP Master.
2. Pastikan port 5050 tidak diblokir firewall.
3. Pastikan jaringan tidak memakai client isolation.
4. Coba hotspot pribadi atau LAN lain.
5. Pastikan Master sudah berjalan.

## 10. Urutan Menjalankan Sistem

### Langkah 1 — Jalankan Master

```bash
./scripts/start_master.sh
```

Keluaran yang diharapkan memuat:

```text
Running on http://127.0.0.1:5050
Running on http://IP-MASTER:5050
```

Buka dashboard:

```text
http://localhost:5050
```

### Langkah 2 — Jalankan sembilan Worker

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_worker.ps1
```

macOS atau Linux:

```bash
./scripts/start_worker.sh
```

Jalankan Worker satu per satu. Setelah setiap Worker menyala, pastikan ID, IP, jumlah proses, CPU, RAM, dan partisinya muncul di dashboard.

### Langkah 3 — Verifikasi jumlah node

Target dashboard:

```text
Master online
Worker online: 9 atau lebih
```

Ambil screenshot yang menampilkan sembilan ID Worker dan IP berbeda.

## 11. Smoke Test

Sebelum menjalankan workload penuh, gunakan dashboard dengan parameter:

| Parameter | Nilai |
|---|---|
| Operation | `raster_aggregate` |
| Scheduling | `dynamic` |
| Tahun awal | 2020 |
| Tahun akhir | 2020 |
| Bulan per task | 1 |
| Jumlah Worker | 9 |

Hasil yang diharapkan:

- 12 task dibuat.
- Task berubah dari pending menjadi running dan completed.
- Progress mencapai 100 persen.
- Failed bernilai 0.
- Hasil agregasi menampilkan 12 bulan.

Jika smoke test gagal, jangan lanjut ke benchmark. Periksa pesan error, partisi, dataset, dan status Worker.

## 12. Job Utama Demo

Gunakan parameter:

| Parameter | Nilai |
|---|---|
| Operation | `raster_aggregate` |
| Scheduling | `dynamic` |
| Tahun awal | 2020 |
| Tahun akhir | 2025 |
| Bulan per task | 1 |
| Jumlah Worker | 9 |

Master membuat 72 task bulanan. Worker yang menyelesaikan task lebih cepat akan menarik task berikutnya sehingga distribusi beban menyesuaikan kemampuan perangkat.

Catat hasil:

- Total bulan.
- Total piksel valid.
- Total dan rata-rata radiansi.
- Minimum dan maksimum radiansi.
- Execution time.
- Distribusi task per Worker.
- CPU dan RAM.

## 13. Bukti Multiprocessing

Saat job berlangsung, buka Task Manager atau Activity Monitor pada minimal satu Worker. Tunjukkan beberapa proses Python dan penggunaan beberapa core CPU.

Konfigurasi yang digunakan harus minimal:

```env
DLUMEN_PROCESSES=2
```

Jelaskan bahwa sembilan Worker adalah sembilan komputer fisik, sedangkan multiprocessing adalah beberapa proses CPU di dalam masing-masing Worker.

## 14. Simulasi Fault Tolerance

Pastikan partisi Worker yang akan dihentikan tersedia pada Worker lain.

### Cara manual

Hentikan terminal salah satu Worker dengan `Ctrl+C` ketika task masih berjalan.

### Cara terkontrol

```bash
curl -X POST http://IP-WORKER:5002/control/stop \
  -H "X-DLUMEN-Token: TOKEN_DEMO" \
  -H "Content-Type: application/json" \
  -d '{"delay":0.5}'
```

Tunjukkan urutan berikut:

1. Worker berhenti mengirim heartbeat.
2. Master menandainya offline.
3. Task Worker tersebut masuk retry atau requeue.
4. Worker lain yang memiliki partisi mengambil task.
5. Task selesai tanpa hasil ganda.
6. Recovery time tercatat.

Event dapat diperiksa pada:

```text
results/runtime/events.jsonl
```

## 15. Benchmark Resmi

### Sequential

```bash
python -m benchmark.run_benchmark \
  --operation raster_aggregate \
  --start-year 2020 --end-year 2025 \
  --processes 1 \
  --output benchmark/sequential
```

Catat `execution_seconds` sebagai `NILAI_T1`.

### Local parallel

```bash
python -m benchmark.run_benchmark \
  --operation raster_aggregate \
  --start-year 2020 --end-year 2025 \
  --processes 4 \
  --baseline-seconds NILAI_T1 \
  --output benchmark/local4
```

### Distributed, static, dynamic, dan scalability

```bash
python -m benchmark.distributed_benchmark \
  --operation raster_aggregate \
  --workers 1,2,4,6,9 \
  --scheduling static,dynamic \
  --repetitions 3 \
  --baseline-seconds NILAI_T1 \
  --output benchmark/distributed
```

Jangan mengubah workload di antara mode. Simpan CSV dan JSON asli sebelum membuat tabel laporan.

## 16. Skenario Video Maksimal Lima Menit

| Waktu | Adegan dan narasi |
|---|---|
| 0:00–0:35 | Tunjukkan 10 perangkat fisik dan topologi satu Master serta sembilan Worker |
| 0:35–1:10 | Dashboard menampilkan sembilan Worker, ID, IP, proses, CPU, RAM |
| 1:10–2:15 | Jalankan job dynamic dan tunjukkan perubahan status task serta hasil agregasi |
| 2:15–2:50 | Tunjukkan Task Manager dan beberapa proses Python pada Worker |
| 2:50–3:40 | Hentikan satu Worker, tunjukkan offline, requeue, Worker pengganti, recovery |
| 3:40–4:35 | Tampilkan CSV, JSON, dan grafik E1–E6 yang sudah dibuat sebelumnya |
| 4:35–5:00 | Sampaikan kesimpulan dan keterbatasan sistem |

Jangan menjalankan seluruh benchmark saat merekam video. Benchmark lengkap dilakukan sebelumnya; saat video cukup demonstrasikan satu job dan satu kegagalan.

## 17. Bukti yang Harus Disimpan

- Foto satu Master dan minimal sembilan Worker fisik.
- Dashboard dengan sembilan Worker online.
- ID, hostname, dan IP berbeda.
- Task Manager atau Activity Monitor multiprocessing.
- Job mencapai progress 100 persen.
- Hasil agregasi VIIRS.
- Worker offline.
- Task retry atau requeue.
- Recovery time.
- Event log JSONL.
- CSV dan JSON benchmark.
- Grafik execution time, speedup, efficiency, throughput, CPU/RAM, dan recovery.
- Keluaran automated test dan `GATE OK`.

## 18. Troubleshooting

| Masalah | Pemeriksaan dan solusi |
|---|---|
| Dashboard tidak terbuka | Pastikan Master aktif dan gunakan port 5050 |
| Worker tidak muncul | Periksa token, URL Master, firewall, VLAN, dan client isolation |
| Worker muncul lalu offline | Periksa koneksi Wi-Fi, heartbeat, dan terminal Worker |
| Job ditolak karena partisi | Sesuaikan `DLUMEN_PARTITIONS` dengan GeoTIFF yang tersedia |
| Raster tidak ditemukan | Periksa `DLUMEN_DATA_DIR` dan nama `VIIRS_Java_YYYY_MM.tif` |
| PostgreSQL gagal | Periksa service, host, port, user, password, lalu jalankan initializer |
| Static job tidak mulai | Pastikan Worker terpilih online dan mempunyai partisi |
| Recovery tidak terjadi | Pastikan Worker pengganti memiliki replika partisi |
| Job terlalu cepat untuk failure demo | Gunakan 2020–2025, satu bulan per task, dan data lengkap |
| IP Master berubah | Perbarui `DLUMEN_MASTER_URL` pada seluruh Worker |

## 19. Checklist Sebelum Mulai Demo

- [ ] Minimal 10 komputer fisik tersedia.
- [ ] Semua perangkat memakai versi source yang sama.
- [ ] Semua perangkat terhubung ke jaringan yang sama.
- [ ] Master readiness menunjukkan siap.
- [ ] Sembilan Worker readiness menunjukkan siap.
- [ ] Token sama dan Worker ID unik.
- [ ] Dataset sesuai metadata partisi.
- [ ] PostgreSQL dan `viirs_monthly` siap.
- [ ] Dashboard menampilkan sembilan Worker online.
- [ ] Smoke test 2020 berhasil tanpa failed task.
- [ ] Benchmark telah disimpan.
- [ ] Partisi fault tolerance mempunyai replika.
- [ ] Kamera dan screen recorder siap.

## 20. Checklist Setelah Demo

- [ ] Salin event log dan seluruh hasil benchmark.
- [ ] Simpan screenshot dan video pada dua lokasi.
- [ ] Isi BAB IV hanya menggunakan hasil nyata.
- [ ] Bedakan pengujian lokal, simulasi, dan node fisik.
- [ ] Jalankan verification gate terakhir.
- [ ] Buat ZIP source tanpa `.env`, `.venv`, cache, atau dataset besar.

Perintah verification terakhir:

```bash
python scripts/gate.py --workers 2
python scripts/pack_source.py
```

Keluaran yang harus diperoleh:

```text
GATE OK
PACKAGE OK
```
