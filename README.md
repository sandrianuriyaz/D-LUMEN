# D-LUMEN — Centralized Master–Worker

D-LUMEN memproses ringkasan VIIRS dengan satu Master (PostgreSQL `dlumen_db`) dan hingga
sembilan Worker fisik di LAN/Wi-Fi. Worker tidak memasang PostgreSQL, `psycopg2`, Flask,
atau Rasterio. Dataset mentah tetap berada di `data/raw/*.tif` pada Master.

Audit dan keputusan migrasi lengkap ada di `docs/REFACTOR_MASTER_WORKER.md`.

## Menyiapkan Master (macOS/Windows)

```bash
python -m venv .venv
# macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-master.txt
python -m preprocessing.viirs_processor
python -m database.init_db
python -m database.import_viirs
python -m database.validate_grid
python -m master.master_server
```

Importer membentuk tabel grid 64×64 di PostgreSQL agar payload benchmark cukup besar untuk
multiprocessing. Jalankan kembali importer setelah menambah GeoTIFF; operasi ini idempotent.

Salin `.env.example` menjadi `.env`, isi kredensial PostgreSQL dan token. Master mendengarkan
`0.0.0.0:5050`; PostgreSQL tidak perlu dan tidak boleh diekspos kepada Worker.

## Menyiapkan setiap Worker

Salin source tanpa folder `data/`, buat virtualenv, lalu `pip install -r requirements-worker.txt`.
Atur `DLUMEN_MASTER_URL=http://IP-MASTER:5050`, `DLUMEN_TOKEN`, dan `DLUMEN_WORKER_ID` unik.
`DLUMEN_PROCESSES` boleh dikosongkan agar memakai `os.cpu_count()`.

```bash
# macOS/Linux
./scripts/start_worker.sh
# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts/start_worker.ps1
```

## Membuat job dan melihat metrik

```bash
curl -X POST http://localhost:5050/jobs \
  -H "X-DLUMEN-Token: $DLUMEN_TOKEN" -H "Content-Type: application/json" \
  -d '{"operation":"aggregate","start_year":2020,"end_year":2025,"worker_count":2}'
curl http://localhost:5050/metrics
```

Operasi: `aggregate`, `extreme` (parameter `threshold`), dan `growth`. Scheduling dapat
`dynamic` (work-pulling) atau `static` untuk pembanding.

## Benchmark enam skenario UAS

```bash
python -m benchmark.run_experiments --start-year 2020 --end-year 2025 \
  --scalability 1,2,4,6,9 --output benchmark/results/uas
```

Untuk dataset workspace saat ini gunakan `--start-year 2024 --end-year 2025`. Runner menjalankan
E1–E6 sebanyak tiga pengulangan, membuat fault injection sebagai skenario terakhir, dan menghasilkan
`*_raw.csv/json`, `*_summary.csv/json`, `*_charts.png`, serta `*_analysis.md`. Worker yang sengaja
dimatikan pada E5 harus dijalankan kembali setelah benchmark selesai.

Skenario fault tolerance memerlukan `--fault-command` yang menghentikan tepat satu Worker.
CSV dan JSON memuat execution time, speedup, efficiency, throughput, CPU/RAM, dan recovery time.
Gunakan `--local-only` untuk hanya menjalankan sequential dan local parallel.

## Verifikasi

```bash
python -m pytest -q
```
