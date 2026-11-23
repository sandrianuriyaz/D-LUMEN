# Arsitektur D-LUMEN

```text
Dashboard/Benchmark Controller
             |
   Master Flask :5050
   - discovery broadcaster
   - worker registry + heartbeat monitor
   - static/dynamic scheduler
   - retry/requeue + idempotent collector
   - result aggregator + event log
             |
     LAN HTTP/JSON + UDP discovery
             |
 Worker 1 ... Worker 9
 - registration/heartbeat/reconnect
 - ProcessPoolExecutor (>=2 proses)
 - PostgreSQL viirs_monthly
 - GeoTIFF partition manager
 - psutil resource metrics
```

Task dipartisi secara horizontal berdasarkan periode bulan. `task_id` mencegah hasil ganda; `partition_id` dan advertised partition membatasi lokasi eksekusi. Replika meningkatkan availability tetapi tidak membuat task tambahan, sehingga tidak menyebabkan double counting.

Dynamic scheduling adalah pull queue: setiap Worker mengambil task sampai seluruh slot proses terisi. Static scheduling menetapkan preferred Worker round-robin; setelah kegagalan, replika kompatibel dapat mengambil task retry. Master tidak mengklaim recovery berhasil jika tidak ada replika.
