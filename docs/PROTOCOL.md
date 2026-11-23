# Protokol D-LUMEN

Transport utama HTTP/JSON; discovery menggunakan UDP broadcast `DLUMEN_MASTER_V2|PORT` pada port 5005. Semua endpoint mutasi memakai header `X-DLUMEN-Token`.

Alur: Worker menemukan Master → `POST /api/register` → heartbeat periodik → `POST /api/tasks/claim` → proses di `ProcessPoolExecutor` → kirim `/result` atau `/fail`. Master hanya menerima hasil pertama dari Worker pemegang task. Timeout/offline mengubah task menjadi `retrying`; Worker lain hanya dapat mengklaim jika metadata partisinya cocok.

Event audit disimpan sebagai JSONL: `worker_registered`, `job_created`, `task_assigned`, `task_completed`, `task_failed`, `duplicate_or_late_result`, `worker_offline`, dan `task_timeout`.
