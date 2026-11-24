# Refactor Master–Worker Terpusat

## Hasil audit

| Area lama | Keputusan | Alasan |
|---|---|---|
| `data/raw/*.tif` | Dipertahankan utuh | Dataset mentah; tidak dipindah atau diubah. |
| `preprocessing/` | Dipertahankan | Pembacaan GeoTIFF dua-band dan validasi piksel masih benar. Hanya dijalankan di Master. |
| `database/schema.sql` | Dipertahankan | Skema bulanan dan indeks sudah idempotent. |
| `database/import_viirs.py` | Dimodifikasi | Loop `INSERT` diganti staging table + PostgreSQL `COPY` + upsert. |
| `parallel/core.py` | Dipertahankan sebagai shared scheduler | Queue thread-safe, retry, status, dan agregasi masih valid; timeout diperbaiki agar mencatat recovery. |
| `parallel/master_app.py` | Diganti secara konseptual | Implementasi aktif sekarang `master/master_server.py`. |
| `parallel/worker_app.py`, `parallel/db.py`, `parallel/raster_workload.py` | Legacy, tidak dipakai Worker baru | Worker lama terhubung PostgreSQL/membaca GeoTIFF lokal dan tidak sesuai arsitektur baru. |
| benchmark lama | Dipertahankan sebagai histori | Runner terpadu baru adalah `benchmark/run_experiments.py`. |

## Arsitektur aktif

PostgreSQL dan seluruh GeoTIFF hanya berada di Master. Master memecah job menjadi periode bulan,
mengambil record terkait dari `dlumen_db`, lalu mengirim payload JSON melalui
`GET /get-task/{worker_id}`. Worker tidak memiliki driver PostgreSQL dan hanya memakai
`requests`, `numpy`, serta `psutil`. Hasil dikirim ke `POST /submit-result`.

Task yang tidak selesai dalam 15 detik kembali ke antrean. Worker lain mengambil task itu
secara otomatis; durasi dari requeue sampai hasil diterima dicatat sebagai recovery time.
Endpoint pengujian utama: `POST /reset`, `GET /metrics`, `GET /status`, dan `POST /jobs`.

Operasi yang tersedia adalah `aggregate` (AVG/MAX/SUM berbobot piksel), `extreme`
(ambang radiance), dan `growth` (pertumbuhan rata-rata tahunan). Dekomposisi default per bulan;
`months_per_task` dapat diperbesar untuk partisi temporal yang lebih kasar.
