"""Non-destructive pre-demo readiness check for Master or Worker nodes."""
from __future__ import annotations

import argparse
import importlib.util
import os
import socket
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE entries without requiring python-dotenv."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def mark(ok: bool, text: str) -> bool:
    print(("[OK]   " if ok else "[FAIL] ") + text)
    return ok


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["master", "worker"], required=True)
    args = parser.parse_args(); checks = []
    checks.append(mark(bool(os.getenv("DLUMEN_TOKEN")), "DLUMEN_TOKEN terisi"))
    modules = ["flask", "requests", "psutil", "psycopg2", "numpy", "rasterio"]
    for module in modules:
        checks.append(mark(importlib.util.find_spec(module) is not None, f"dependency {module}"))
    print(f"[INFO] hostname={socket.gethostname()} cpu={os.cpu_count() or 'unknown'}")
    if args.role == "worker":
        data_dir = Path(os.getenv("DLUMEN_DATA_DIR", "data/raw"))
        files = list(data_dir.glob("VIIRS_Java_*.tif"))
        checks.append(mark(bool(files), f"GeoTIFF tersedia: {len(files)} file di {data_dir}"))
        checks.append(mark(int(os.getenv("DLUMEN_PROCESSES", "1")) >= 2,
                           "DLUMEN_PROCESSES minimal 2"))
        print(f"[INFO] worker_id={os.getenv('DLUMEN_WORKER_ID') or 'otomatis hostname+MAC'}")
        print(f"[INFO] partitions={os.getenv('DLUMEN_PARTITIONS') or 'semua (pastikan data lengkap)'}")
        try:
            from parallel.db import connection
            with connection() as conn, conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM viirs_monthly")
                rows = cursor.fetchone()[0]
            checks.append(mark(rows > 0, f"PostgreSQL viirs_monthly: {rows} baris"))
        except Exception as exc:
            checks.append(mark(False, f"PostgreSQL belum siap: {type(exc).__name__}: {exc}"))
    else:
        print(f"[INFO] master_port={os.getenv('DLUMEN_MASTER_PORT', '5050')}")
    print(f"\n{'SIAP' if all(checks) else 'BELUM SIAP'}: {sum(checks)}/{len(checks)} pemeriksaan lulus")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
