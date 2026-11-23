# D-LUMEN

Distributed database processing untuk ringkasan VIIRS Nighttime Lights. Prototipe menyediakan discovery otomatis, registry/heartbeat, partisi temporal, static/dynamic scheduling, multiprocessing worker, retry/requeue, idempotent result, dashboard, dan benchmark lokal.

## Setup

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Pada setiap Worker yang memakai query PostgreSQL, buat database `dlumen_db`, lalu jalankan schema dan import data (keduanya aman dijalankan ulang):

```bash
python -m database.init_db
python -m database.import_viirs
```

Salin `.env.example` ke `.env`. Gunakan token acak yang sama di seluruh node. Sandria memakai `DLUMEN_DB_HOST=/tmp`, `DLUMEN_DB_USER=sandrianuriya`; Windows memakai host `127.0.0.1`, user `postgres`, port 5432/5433, dan password hanya di environment lokal.

## Menjalankan

Mac master: `chmod +x scripts/*.sh && ./scripts/start_master.sh`. Dashboard: `http://localhost:5050`.

Worker macOS: `./scripts/start_worker.sh`. Worker Kenanga/Fawwaz: `powershell -ExecutionPolicy Bypass -File scripts/start_worker.ps1`. Beri `DLUMEN_WORKER_ID` unik. Worker ke-3 sampai ke-9 memakai source dan token yang sama; tidak perlu edit source. Jika UDP diblokir AP isolation/VLAN/firewall, isi `DLUMEN_MASTER_URL=http://IP-MASTER:5050` (fallback eksplisit, bukan scanning).

Buat job dari master:

```bash
curl -X POST http://localhost:5050/api/jobs -H "X-DLUMEN-Token: $DLUMEN_TOKEN" -H 'Content-Type: application/json' -d '{"operation":"aggregate","start_year":2020,"end_year":2025,"months_per_task":1,"scheduling":"dynamic"}'
curl http://localhost:5050/api/results
```

Atau: `.venv/bin/python -m parallel.distributed_query --operation aggregate --scheduling dynamic --wait`.

Operation: `aggregate`, `search`, `highest`, `lowest`, `annual`, `trend`, dan `raster_aggregate`. Mode raster membaca seluruh piksel GeoTIFF per bulan dan menghitung statistik serta histogram; gunakan mode ini untuk workload UAS yang lebih representatif. Filter search dapat dimasukkan pada `params`: `min_mean`, `max_mean`, `limit`.

## Arti 10 node fisik

Node adalah satu komputer/perangkat independen yang mempunyai OS, CPU, RAM, dan koneksi jaringan sendiri. Susunan minimal adalah **1 komputer Master + 9 komputer Worker = 10 komputer fisik**. Sembilan terminal, container, VM, atau proses pada MacBook yang sama tidak dihitung sebagai sembilan node fisik. Master Sandria boleh sekaligus menjalankan database lokal, tetapi untuk pembuktian yang aman jangan dihitung lagi sebagai Worker.

Contoh topologi: laptop Sandria sebagai Master; laptop Kenanga dan Fawwaz sebagai Worker 1–2; enam PC laboratorium sebagai Worker 3–8; satu laptop tambahan sebagai Worker 9. Semuanya tersambung ke Wi-Fi/LAN yang sama dan terlihat sebagai sembilan `worker_id`/hostname berbeda di dashboard.

Untuk dataset terbagi, isi `DLUMEN_PARTITIONS=2020,2021` pada node Sandria, `2022,2023` pada Kenanga, dan seterusnya. Benchmark scalability 1/2/4/6/9 membutuhkan seluruh workload dapat diakses pada setiap konfigurasi; cara paling sederhana adalah menyalin dataset yang sama ke sembilan Worker. Untuk eksperimen fault tolerance, setiap partisi harus tersedia minimal pada dua Worker.

Test discovery dengan mengosongkan `DLUMEN_MASTER_URL`, jalankan master/worker pada LAN yang sama, lalu periksa `/api/workers`. Fault tolerance: mulai job dengan replika tersedia pada minimal dua worker, hentikan proses worker yang sedang running, tunggu heartbeat timeout, dan amati `retrying` lalu `completed`. Tanpa partisi replika, task tetap pending secara jujur.

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m benchmark.run_benchmark --processes 1 --output benchmark/sequential
.venv/bin/python -m benchmark.run_benchmark --processes 4 --baseline-seconds NILAI_T1 --output benchmark/local4
.venv/bin/python -m benchmark.plot_results benchmark/sequential.csv benchmark/local4.csv --output benchmark/comparison.png
```

Workload piksel nyata dan benchmark distributed resmi:

```bash
.venv/bin/python -m benchmark.run_benchmark --operation raster_aggregate --start-year 2020 --end-year 2021 --processes 1 --output benchmark/raster-sequential
.venv/bin/python -m benchmark.distributed_benchmark --operation raster_aggregate --workers 1,2,4,6,9 --scheduling static,dynamic --repetitions 3 --baseline-seconds NILAI_T1 --output benchmark/distributed
```

Benchmark runner hanya menulis hasil pengukuran nyata ke CSV/JSON. Eksperimen distributed fisik dan grafik baru boleh dibuat setelah node tersedia. Lihat `docs/UAS_REPORT.md`.

## Gate dan pengumpulan

```bash
python scripts/gate.py --quick          # compile + automated tests
python scripts/gate.py --workers 2      # termasuk E2E Master/Worker nyata
python scripts/pack_source.py           # ZIP tanpa .env/.venv/GeoTIFF/cache
```

Panduan demo fisik ada di `docs/DEPLOYMENT-PHYSICAL.md`; protokol di `docs/PROTOCOL.md`; strategi test di `docs/TESTING.md`; skenario eksperimen di `docs/EXPERIMENTS.md`.
