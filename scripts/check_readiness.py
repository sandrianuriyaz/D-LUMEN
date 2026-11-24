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
    modules = (["flask", "requests", "psutil", "psycopg2", "numpy", "rasterio"]
               if args.role == "master" else ["requests", "psutil", "numpy"])
    for module in modules:
        checks.append(mark(importlib.util.find_spec(module) is not None, f"dependency {module}"))
    print(f"[INFO] hostname={socket.gethostname()} cpu={os.cpu_count() or 'unknown'}")
    if args.role == "worker":
        checks.append(mark(bool(os.getenv("DLUMEN_MASTER_URL")), "DLUMEN_MASTER_URL terisi"))
        print(f"[INFO] worker_id={os.getenv('DLUMEN_WORKER_ID') or 'otomatis hostname+MAC'}")
        worker_source = Path("worker/worker_node.py").read_text(encoding="utf-8")
        checks.append(mark("psycopg2" not in worker_source,
                           "kode Worker tidak bergantung pada psycopg2"))
    else:
        print(f"[INFO] master_port={os.getenv('DLUMEN_MASTER_PORT', '5050')}")
    print(f"\n{'SIAP' if all(checks) else 'BELUM SIAP'}: {sum(checks)}/{len(checks)} pemeriksaan lulus")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
