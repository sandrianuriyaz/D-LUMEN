"""Run and export the six required UAS performance scenarios using real measurements."""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
import requests

from master.repository import ViirsRepository
from worker.worker_node import compute_chunk, merge_results


def partitions(start: int, end: int) -> list[dict[str, int]]:
    return [{"start_year": y, "start_month": m, "end_year": y, "end_month": m}
            for y in range(start, end + 1) for m in range(1, 13)]


def local_run(processes: int, args) -> dict[str, Any]:
    repository = ViirsRepository(); payloads = [repository.payload(p)["records"] for p in partitions(args.start_year, args.end_year)]
    before = psutil.virtual_memory().percent; psutil.cpu_percent(interval=None); started = time.perf_counter()
    if processes == 1:
        values = [compute_chunk(args.operation, rows, {}) for rows in payloads]
    else:
        with ProcessPoolExecutor(max_workers=processes) as pool:
            values = list(pool.map(compute_chunk, [args.operation] * len(payloads), payloads, [{}] * len(payloads)))
    elapsed = time.perf_counter() - started
    return {"execution_time_seconds": elapsed, "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": (before + psutil.virtual_memory().percent) / 2,
            "completed_tasks": len(values), "result": merge_results(values, args.operation)}


def distributed_run(session: requests.Session, args, workers: int, scheduling: str,
                    fault_command: str | None = None) -> dict[str, Any]:
    session.post(args.master + "/reset", timeout=10).raise_for_status()
    response = session.post(args.master + "/jobs", json={"operation": args.operation,
        "start_year": args.start_year, "end_year": args.end_year, "months_per_task": args.months_per_task,
        "worker_count": workers, "scheduling": scheduling}, timeout=15)
    response.raise_for_status(); job_id = response.json()["job_id"]
    started = time.perf_counter(); fault_started = False
    while True:
        status = session.get(args.master + "/status", params={"job_id": job_id}, timeout=15).json()
        counts = status["tasks"]; total = sum(counts.values())
        if fault_command and not fault_started and counts["running"]:
            subprocess.Popen(fault_command, shell=True); fault_started = True
        if total and counts["completed"] + counts["failed"] == total: break
        if time.perf_counter() - started > args.timeout: raise TimeoutError(f"job {job_id} timeout")
        time.sleep(args.poll_interval)
    elapsed = time.perf_counter() - started
    metrics = session.get(args.master + "/metrics", timeout=15).json()
    return {"execution_time_seconds": elapsed, "cpu_percent": metrics["mean_cpu_percent"],
            "memory_percent": metrics["mean_memory_percent"], "recovery_time_seconds": metrics["recovery_time_seconds"],
            "completed_tasks": counts["completed"], "failed_tasks": counts["failed"], "job_id": job_id}


def record(name: str, processors: int, measurement: dict[str, Any], baseline: float) -> dict[str, Any]:
    elapsed = measurement["execution_time_seconds"]; speedup = baseline / elapsed
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "scenario": name,
        "workers_or_processes": processors, "execution_time_seconds": elapsed, "speedup": speedup,
        "efficiency": speedup / processors, "throughput_tasks_second": measurement["completed_tasks"] / elapsed,
        "cpu_percent": measurement.get("cpu_percent"), "memory_percent": measurement.get("memory_percent"),
        "recovery_time_seconds": measurement.get("recovery_time_seconds"),
        "completed_tasks": measurement["completed_tasks"], "failed_tasks": measurement.get("failed_tasks", 0)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=os.getenv("DLUMEN_MASTER_URL", "http://127.0.0.1:5050"))
    parser.add_argument("--start-year", type=int, default=2020); parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--operation", choices=["aggregate", "extreme", "growth"], default="aggregate")
    parser.add_argument("--months-per-task", type=int, default=1); parser.add_argument("--local-processes", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--scalability", default="1,2,4,6,9"); parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=.5); parser.add_argument("--output", default="benchmark/results/experiments")
    parser.add_argument("--fault-command", help="Perintah untuk mematikan satu Worker saat task RUNNING")
    parser.add_argument("--local-only", action="store_true", help="Jalankan skenario 1-2 tanpa Master/Worker")
    args = parser.parse_args(); args.master = args.master.rstrip("/")
    sequential = local_run(1, args); baseline = sequential["execution_time_seconds"]
    rows = [record("1_sequential", 1, sequential, baseline)]
    local = local_run(args.local_processes, args)
    rows.append(record("2_local_parallel", args.local_processes, local, baseline))
    if not args.local_only:
        session = requests.Session(); token = os.getenv("DLUMEN_TOKEN", "")
        if token: session.headers["X-DLUMEN-Token"] = token
        distributed = distributed_run(session, args, 2, "static")
        rows.append(record("3_distributed", 2, distributed, baseline))
        dynamic = distributed_run(session, args, 2, "dynamic")
        rows.append(record("4_dynamic_load_balancing", 2, dynamic, baseline))
        if args.fault_command:
            fault = distributed_run(session, args, 2, "dynamic", args.fault_command)
            rows.append(record("5_fault_tolerance", 2, fault, baseline))
        else:
            print("Skenario 5 dilewati: berikan --fault-command untuk mematikan satu Worker.")
        for count in map(int, args.scalability.split(",")):
            value = distributed_run(session, args, count, "dynamic")
            rows.append(record(f"6_scalability_{count}_workers", count, value, baseline))
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__": main()
