"""Real localhost E2E: Master + N Worker processes + VIIRS raster job."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until(fn, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except Exception as exc:
            last = exc
        time.sleep(.25)
    raise TimeoutError(f"condition timeout; last={last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--processes", type=int, default=2)
    parser.add_argument("--year", type=int, default=2020)
    args = parser.parse_args()
    if not 1 <= args.workers <= 9:
        raise SystemExit("--workers harus 1..9")
    token = "e2e-local-token"; master_port = free_port(); base = f"http://127.0.0.1:{master_port}"
    run_dir = Path(tempfile.mkdtemp(prefix="dlumen-e2e-")); processes = []; logs = []
    common = os.environ.copy(); common.update(PYTHONUNBUFFERED="1", DLUMEN_TOKEN=token,
        DLUMEN_MASTER_PORT=str(master_port), DLUMEN_MASTER_URL=base,
        DLUMEN_DATA_DIR=str(ROOT/"data"/"raw"), DLUMEN_PARTITIONS=str(args.year),
        DLUMEN_HEARTBEAT_TIMEOUT="3", DLUMEN_TASK_TIMEOUT="60",
        DLUMEN_EVENT_LOG=str(run_dir/"events.jsonl"))
    try:
        master_log = (run_dir/"master.log").open("w", encoding="utf-8"); logs.append(master_log)
        processes.append(subprocess.Popen([sys.executable, "-m", "parallel.master_app"], cwd=ROOT,
            env=common, stdout=master_log, stderr=subprocess.STDOUT))
        wait_until(lambda: requests.get(base+"/health", timeout=1).status_code == 200)
        for index in range(args.workers):
            env = common.copy(); env.update(DLUMEN_WORKER_ID=f"e2e-w{index+1}",
                DLUMEN_WORKER_PORT=str(free_port()), DLUMEN_PROCESSES=str(args.processes))
            log = (run_dir/f"worker-{index+1}.log").open("w", encoding="utf-8"); logs.append(log)
            processes.append(subprocess.Popen([sys.executable, "-m", "parallel.worker_app"], cwd=ROOT,
                env=env, stdout=log, stderr=subprocess.STDOUT))
        wait_until(lambda: len([w for w in requests.get(base+"/api/workers", timeout=2).json() if w["online"]]) == args.workers)
        response = requests.post(base+"/api/jobs", headers={"X-DLUMEN-Token": token}, timeout=5,
            json={"operation":"raster_aggregate", "start_year":args.year, "end_year":args.year,
                  "months_per_task":1, "worker_count":args.workers, "scheduling":"dynamic"})
        response.raise_for_status(); job_id = response.json()["job_id"]
        status = wait_until(lambda: _completed_status(base, job_id), timeout=120)
        expected = json.loads((ROOT/"data"/"processed"/"viirs_summary.json").read_text())
        expected = [r for r in expected if r["year"] == args.year]
        aggregate = status["aggregate"]
        assert aggregate["months"] == len(expected), (aggregate, len(expected))
        assert aggregate["valid_pixels"] == sum(r["valid_pixels"] for r in expected)
        assert status["tasks"]["failed"] == 0
        print(f"E2E OK: {args.workers} workers, {aggregate['months']} months, "
              f"{aggregate['valid_pixels']} pixels; evidence={run_dir}")
        return 0
    except Exception:
        print(f"E2E FAILED; logs={run_dir}", file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill()
        for log in logs: log.close()


def _completed_status(base: str, job_id: str):
    status = requests.get(base+"/api/status", params={"job_id": job_id}, timeout=2).json()
    counts = status["tasks"]
    return status if sum(counts.values()) and counts["completed"]+counts["failed"] == sum(counts.values()) else None


if __name__ == "__main__":
    raise SystemExit(main())
