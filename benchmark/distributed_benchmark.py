"""Controller for real distributed UAS experiments (no synthetic data)."""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def wait_job(base, job_id, timeout, sample_interval=1.0):
    started = time.perf_counter(); cpu, memory = [], []
    while True:
        status = requests.get(f"{base}/api/status", params={"job_id": job_id}, timeout=15).json()
        if status.get("error"): raise RuntimeError(status["error"])
        metrics = status["metrics"]
        if metrics["mean_cpu_percent"] is not None: cpu.append(metrics["mean_cpu_percent"])
        if metrics["mean_memory_percent"] is not None: memory.append(metrics["mean_memory_percent"])
        counts = status["tasks"]; total = sum(counts.values())
        if total and counts["completed"] + counts["failed"] == total:
            return status, time.perf_counter()-started, cpu, memory
        if time.perf_counter()-started > timeout: raise TimeoutError(f"job {job_id} melewati {timeout}s")
        time.sleep(sample_interval)


def run_once(base, headers, workers, scheduling, args, repetition):
    payload = {"operation": args.operation, "start_year": args.start_year, "end_year": args.end_year,
               "months_per_task": args.months_per_task, "worker_count": workers, "scheduling": scheduling}
    submitted = requests.post(f"{base}/api/jobs", headers=headers, json=payload, timeout=15)
    submitted.raise_for_status(); job = submitted.json()
    status, elapsed, cpu, memory = wait_job(base, job["job_id"], args.timeout)
    recovery_values = [e["recovery_seconds"] for e in status["recovery"] if e["recovery_seconds"] is not None]
    workload = (args.end_year-args.start_year+1)*12
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "job_id": job["job_id"],
            "mode": "distributed", "scheduling": scheduling, "workers": workers,
            "worker_ids": ";".join(job["worker_ids"]), "repetition": repetition,
            "workload_months": workload, "execution_seconds": elapsed,
            "throughput_months_sec": workload/elapsed, "mean_cpu_percent": statistics.fmean(cpu) if cpu else None,
            "mean_memory_percent": statistics.fmean(memory) if memory else None,
            "recovery_seconds": max(recovery_values) if recovery_values else None,
            "completed": status["tasks"]["completed"], "failed": status["tasks"]["failed"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--master", default=os.getenv("DLUMEN_MASTER_URL", "http://127.0.0.1:5050"))
    p.add_argument("--workers", default="1,2,4,6,9")
    p.add_argument("--scheduling", default="static,dynamic")
    p.add_argument("--repetitions", type=int, default=3); p.add_argument("--timeout", type=float, default=1800)
    p.add_argument("--operation", default="aggregate"); p.add_argument("--start-year", type=int, default=2020)
    p.add_argument("--end-year", type=int, default=2025); p.add_argument("--months-per-task", type=int, default=1)
    p.add_argument("--baseline-seconds", type=float); p.add_argument("--output", default="benchmark/distributed")
    args = p.parse_args(); token = os.getenv("DLUMEN_TOKEN")
    if not token: raise SystemExit("DLUMEN_TOKEN wajib diatur")
    base = args.master.rstrip("/"); headers = {"X-DLUMEN-Token": token}; rows = []
    for count in map(int, args.workers.split(",")):
        for scheduling in args.scheduling.split(","):
            for repetition in range(1, args.repetitions+1):
                row = run_once(base, headers, count, scheduling, args, repetition)
                if args.baseline_seconds:
                    row["speedup"] = args.baseline_seconds/row["execution_seconds"]
                    row["efficiency"] = row["speedup"]/count
                else: row.update(speedup=None, efficiency=None)
                rows.append(row); print(json.dumps(row, indent=2))
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)


if __name__ == "__main__": main()
