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

Perintah distributed:

```bash
python -m benchmark.distributed_benchmark --operation raster_aggregate \
  --workers 1,2,4,6,9 --scheduling static,dynamic --repetitions 3 \
  --baseline-seconds NILAI_E1 --output benchmark/distributed
```
