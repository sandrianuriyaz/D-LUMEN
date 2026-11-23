"""Run real benchmarks; never synthesizes measurements."""
from __future__ import annotations

import argparse
import csv
import json
import time
import threading
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from parallel.db import execute_operation
from parallel.raster_workload import analyze_raster


def timed(fn, *args):
    start = time.perf_counter(); result = fn(*args)
    return result, time.perf_counter()-start


def run_local(processes: int, start_year: int, end_year: int, operation="aggregate"):
    partitions = [{"start_year": y, "start_month": m, "end_year": y, "end_month": m}
                  for y in range(start_year, end_year+1) for m in range(1, 13)]
    function = analyze_raster if operation == "raster_aggregate" else _aggregate
    samples = {"cpu": [], "memory": []}; stop = threading.Event()
    def sample_resources():
        try:
            import psutil
            while not stop.wait(.1):
                samples["cpu"].append(psutil.cpu_percent())
                samples["memory"].append(psutil.virtual_memory().percent)
        except ImportError: pass
    threading.Thread(target=sample_resources, daemon=True).start()
    try:
        import psutil
        process = psutil.Process(); cpu_before = process.cpu_times(); memory_before = process.memory_info().rss
    except ImportError: process = cpu_before = None; memory_before = None
    start = time.perf_counter()
    if processes == 1:
        results = [function(p) for p in partitions]
    else:
        with ProcessPoolExecutor(max_workers=processes) as pool:
            results = list(pool.map(function, partitions))
    elapsed = time.perf_counter()-start; stop.set()
    cpu_seconds = None
    if process:
        after = process.cpu_times(); cpu_seconds = (after.user+after.system)-(cpu_before.user+cpu_before.system)
    return results, elapsed, cpu_seconds, memory_before, samples


def _aggregate(params): return execute_operation("aggregate", params)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--processes", type=int, default=1)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--baseline-seconds", type=float)
    parser.add_argument("--operation", choices=["aggregate", "raster_aggregate"], default="aggregate")
    parser.add_argument("--output", default="benchmark/results")
    args = parser.parse_args()
    results, elapsed, cpu_seconds, memory_bytes, samples = run_local(args.processes, args.start_year, args.end_year, args.operation)
    workload = (args.end_year-args.start_year+1)*12
    speedup = args.baseline_seconds/elapsed if args.baseline_seconds else None
    record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "mode": "sequential" if args.processes == 1 else "local_parallel",
              "processors": args.processes, "workload_months": workload,
              "execution_seconds": elapsed, "throughput_months_sec": workload/elapsed,
              "operation": args.operation, "cpu_time_seconds": cpu_seconds,
              "memory_rss_bytes_start": memory_bytes,
              "mean_cpu_percent": sum(samples["cpu"])/len(samples["cpu"]) if samples["cpu"] else None,
              "mean_memory_percent": sum(samples["memory"])/len(samples["memory"]) if samples["memory"] else None,
              "speedup": speedup, "efficiency": speedup/args.processes if speedup else None,
              "result_partitions": len(results)}
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=record); writer.writeheader(); writer.writerow(record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__": main()
