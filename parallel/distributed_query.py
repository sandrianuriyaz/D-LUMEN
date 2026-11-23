"""Submit distributed queries without hardcoded worker IPs."""
import argparse
import json
import os
import time
import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--master", default=os.getenv("DLUMEN_MASTER_URL", "http://127.0.0.1:5050"))
    p.add_argument("--operation", choices=["aggregate", "search", "highest", "lowest", "annual", "trend", "raster_aggregate"], default="aggregate")
    p.add_argument("--start-year", type=int, default=2020); p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--months-per-task", type=int, default=1)
    p.add_argument("--scheduling", choices=["static", "dynamic"], default="dynamic")
    p.add_argument("--wait", action="store_true"); args = p.parse_args()
    token = os.getenv("DLUMEN_TOKEN")
    if not token: raise SystemExit("DLUMEN_TOKEN wajib diatur")
    base = args.master.rstrip("/"); headers = {"X-DLUMEN-Token": token}
    payload = {"operation": args.operation, "start_year": args.start_year, "end_year": args.end_year,
               "months_per_task": args.months_per_task, "scheduling": args.scheduling}
    response = requests.post(base+"/api/jobs", json=payload, headers=headers, timeout=15)
    response.raise_for_status(); print(json.dumps(response.json(), indent=2))
    while args.wait:
        status = requests.get(base+"/api/status", timeout=10).json(); print(json.dumps(status, indent=2))
        terminal = status["tasks"]["completed"] + status["tasks"]["failed"]
        if sum(status["tasks"].values()) and terminal == sum(status["tasks"].values()): break
        time.sleep(2)


if __name__ == "__main__": main()
