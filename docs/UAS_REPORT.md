# D-LUMEN — Dokumentasi Teknis dan Template Laporan UAS

## BAB I — Pendahuluan

D-LUMEN memproses data VIIRS Nighttime Lights 2024–2025 secara terdistribusi. GeoTIFF dibagi menjadi grid 64×64 dan dimuat ke PostgreSQL Master, lalu payload grid diproses Worker tanpa koneksi database langsung.

## BAB II — Studi Pustaka

Landasan yang digunakan: arsitektur master–worker; partisi horizontal berbasis waktu; weighted global mean (`sum(sum_radiance) / sum(valid_pixels)`); multiprocessing Python; PostgreSQL; HTTP/JSON; UDP broadcast; heartbeat; bounded retry; speedup `T1/Tp`; efficiency `speedup/p`; throughput `unit pekerjaan/waktu`.

Rujukan resmi awal: [NASA Earthdata/CMR VIIRS Nighttime Lights](https://cmr.earthdata.nasa.gov/search/site/collections/directory/LAADS/gov.nasa.eosdis), [Python ProcessPoolExecutor](https://docs.python.org/3/library/concurrent.futures.html), dan [PostgreSQL Aggregate Functions](https://www.postgresql.org/docs/current/functions-aggregate.html). Tambahkan dokumentasi resmi Flask, psutil, Rasterio, NumPy, dan Matplotlib beserta tanggal akses pada daftar pustaka final.

## BAB III — Metodologi

Worker mendaftar ke URL Master, mengirim heartbeat dan metrik pada thread terpisah, kemudian menarik task melalui HTTP. Dynamic scheduling memakai pull queue sehingga Worker cepat menarik lebih banyak task; static scheduling memasang satu Worker per task secara round-robin. Task memiliki UUID, partition ID, parameter, status, attempt, dan Worker. Result diterima tepat sekali per task ID.

Partisi default adalah bulan, dapat digabung dengan `months_per_task`. Metadata `replicas` membatasi task hanya ke worker yang punya partisi. Jika tidak ada replika tersedia, task tetap pending—tidak diklaim pulih. Replikasi harus disiapkan sebelum eksperimen (salinan tabel/GeoTIFF atau storage bersama), lalu daftar partisi worker di `DLUMEN_PARTITIONS`.

Pengukuran wajib memakai workload identik dan memisahkan persiapan data dari query. Catat CPU/RAM dari psutil, waktu dinding, throughput, recovery time dari worker offline sampai task selesai ulang, serta `p`: jumlah proses untuk local parallel atau jumlah worker fisik aktif untuk distributed.

Workload utama memakai 9.679 grid PostgreSQL hasil 24 GeoTIFF. Setiap task membawa ratusan record grid dan Worker membaginya ke seluruh core lokal. Kernel numerik deterministik dengan `work_factor` menjaga hasil ilmiah count/sum/min/max tetap sama sambil menyediakan beban CPU terkontrol untuk perbandingan yang adil.

## BAB IV — Hasil dan Pembahasan (isi hanya dari eksperimen nyata)

| Mode | Worker fisik | Proses/worker | Waktu (s) | Speedup | Efficiency | Throughput | CPU | RAM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sequential | 1 | 1 | TBD | 1.0 | 1.0 | TBD | TBD | TBD |

Tambahkan grafik dari CSV hasil nyata untuk sequential, local parallel, distributed, static/dynamic, fault tolerance, serta 1/2/4/6/9 worker. Jelaskan bottleneck jaringan/database dan skew data; jangan mengisi angka simulasi sebagai hasil fisik.

## Kesimpulan

Isi setelah benchmark 10 node. Bedakan bukti unit/integration mock dengan eksperimen fisik.

## Checklist eksperimen 10 node

- [ ] 1 master + 9 komputer worker fisik tercatat dengan hostname/IP berbeda
- [ ] firewall membuka TCP 5050; AP isolation/VLAN diperiksa
- [ ] grid PostgreSQL diverifikasi, total 24 bulan/9.679 chunk tanpa duplikat
- [ ] sequential dan local multiprocessing dijalankan
- [ ] distributed 1/2/4/6/9 worker dengan workload identik
- [ ] static versus dynamic, minimal 3 pengulangan
- [ ] satu worker dimatikan saat running; retry, worker pengganti, dan recovery time direkam
- [ ] CSV, JSON, grafik, log, screenshot dashboard dan Task Manager/Activity Monitor disimpan

## Demo 5 menit

0:00 arsitektur/topologi; 0:45 jalankan master; 1:00 worker auto-discovery; 1:40 buat job dynamic; 2:20 dashboard/result; 3:00 matikan satu worker dan tunjukkan requeue; 4:00 tampilkan benchmark nyata; 4:40 simpulan.

## Pengumpulan

Salin source tanpa `.venv`, `.env`, raw GeoTIFF besar, password, dan cache. Sertakan `.env.example`, requirements, source, tests, dokumentasi, CSV/JSON/grafik eksperimen nyata, serta README. Screenshot: topologi fisik, daftar 9 worker, task lifecycle, utilisasi tiap node, hasil setiap mode, recovery, dan grafik.
