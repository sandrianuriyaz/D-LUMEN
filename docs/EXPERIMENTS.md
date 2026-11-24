# Rancangan Eksperimen E1–E6

Gunakan workload, periode data, granularitas, dan hasil ilmiah yang sama. Persiapan/copy data dilakukan sebelum timer. Jalankan minimal tiga ulangan dan laporkan mean serta simpangan baku.

| ID | Eksperimen | Variasi |
|---|---|---|
| E1 | Sequential baseline | 1 proses |
| E2 | Local parallel | 2, 4, dan jumlah core yang relevan |
| E3 | Distributed | 9 Worker, dynamic |
| E4 | Load balancing | static vs dynamic, workload sama |
| E5 | Fault tolerance | tanpa kegagalan vs satu Worker dihentikan |
| E6 | Scalability | 1, 2, 4, 6, 9 Worker |

Metrik: execution time, `speedup=T1/Tp`, `efficiency=speedup/p`, throughput bulan/detik, CPU/RAM, recovery time, retries, failed tasks, dan pembagian task per Worker. Untuk local parallel, `p` adalah proses; untuk distributed, `p` adalah Worker fisik aktif. Jangan mencampur kedua definisi pada satu grafik efficiency.

Perintah benchmark final (grid PostgreSQL, tiga pengulangan, E1-E6):

```bash
python -m benchmark.run_experiments --start-year 2024 --end-year 2025 \
  --local-processes 2,4,8 --scalability 1,2,4,6,9 --repetitions 3 \
  --work-factor 100000 --output benchmark/results/uas
```

E5 dijalankan terakhir. Runner mengirim fault injection terautentikasi melalui Master kepada
satu Worker yang sedang `RUNNING`; proses Worker benar-benar berhenti, heartbeat timeout memicu
requeue, dan Worker lain menyelesaikan task. Jalankan kembali Worker yang dihentikan sesudah benchmark.
