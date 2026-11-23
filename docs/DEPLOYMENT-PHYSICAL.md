# Runbook Demo Fisik D-LUMEN (1 Master + 9 Worker)

## Sebelum masuk laboratorium

1. Salin source dan dataset ke setiap komputer; jangan salin `.env` berisi secret antar kelompok.
2. Jalankan `scripts/setup_node.ps1` (Windows) atau `scripts/setup_node.sh` (macOS/Linux).
3. Salin `.env.example` menjadi `.env`. Gunakan token yang sama, Worker ID berbeda, dan `DLUMEN_PROCESSES>=2`.
4. Jika seluruh Worker punya dataset lengkap, isi `DLUMEN_PARTITIONS=2020,2021,2022,2023,2024,2025`.
5. Jalankan `python scripts/check_readiness.py --role worker`; semua pemeriksaan harus `OK`.

## Jaringan

- Hubungkan 10 komputer ke satu LAN/hotspot tanpa client isolation.
- Master membuka TCP 5050 dan UDP 5005; Worker membuka TCP 5002 (atau port unik bila diperlukan).
- Catat IP Master (`ipconfig getifaddr en0` di macOS; `ipconfig` di Windows).
- Gunakan fallback `DLUMEN_MASTER_URL=http://IP-MASTER:5050` untuk demo yang paling stabil.
- Uji dari Worker: buka `http://IP-MASTER:5050/health` dan pastikan status `online`.

## Menjalankan

1. Master: `./scripts/start_master.sh`.
2. Sembilan Worker Windows: `powershell -ExecutionPolicy Bypass -File scripts/start_worker.ps1`.
3. Tunggu dashboard menunjukkan `Worker online: 9`; foto hostname/IP/proses.
4. Jalankan job kecil satu tahun sebagai smoke, lalu job resmi 2020–2025.

## Eksperimen wajib

- Sequential dan local parallel: `benchmark.run_benchmark`.
- Distributed/scalability/static-dynamic: `benchmark.distributed_benchmark` dengan 1,2,4,6,9 Worker dan 3 ulangan.
- Fault tolerance: saat task berjalan, panggil `POST http://IP-WORKER:5002/control/stop` dengan header token, atau hentikan terminal Worker. Pastikan event `worker_offline`, task requeue, dan recovery tercatat.
- Simpan `results/runtime/events.jsonl`, CSV/JSON benchmark, grafik, screenshot, dan log terminal.

## Troubleshooting cepat

| Gejala | Tindakan |
|---|---|
| Worker tidak muncul | Cek token, URL Master, firewall, VLAN/AP isolation |
| Job ditolak partisi | Pastikan `DLUMEN_PARTITIONS` sesuai GeoTIFF lokal |
| Database gagal | Jalankan `python -m database.init_db` lalu import data |
| Port bentrok | Master 5050; beri `DLUMEN_WORKER_PORT` unik |
| Task terlalu cepat | Gunakan 2020–2025 dan granularitas satu bulan |
| Recovery tidak jalan | Pastikan partisi tersedia pada Worker pengganti |
