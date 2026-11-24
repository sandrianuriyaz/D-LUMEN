"""Controlled E1-E6 UAS benchmark with raw, summary, plot, and analysis outputs."""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import psutil
import requests

from master.repository import ViirsRepository
from worker.worker_node import compute_chunk, merge_results


def periods(start: int, end: int) -> list[dict[str, int]]:
    return [{"start_year": year, "start_month": month, "end_year": year, "end_month": month,
             "payload_mode": "grid"}
            for year in range(start, end + 1) for month in range(1, 13)]


def sample_resources(stop: threading.Event, samples: dict[str, list[float]]) -> None:
    psutil.cpu_percent(interval=None)
    while not stop.wait(.1):
        samples["cpu"].append(psutil.cpu_percent(interval=None))
        samples["memory"].append(psutil.virtual_memory().percent)


def local_run(processes: int, args) -> dict[str, Any]:
    repository = ViirsRepository()
    payloads = [repository.payload(params)["records"] for params in periods(args.start_year, args.end_year)]
    task_params = {"work_factor": args.work_factor}
    stop = threading.Event(); samples = {"cpu": [], "memory": []}
    sampler = threading.Thread(target=sample_resources, args=(stop, samples), daemon=True); sampler.start()
    started = time.perf_counter()
    if processes == 1:
        values = [compute_chunk(args.operation, records, task_params) for records in payloads]
    else:
        with ProcessPoolExecutor(max_workers=processes) as pool:
            values = list(pool.map(compute_chunk, [args.operation] * len(payloads), payloads,
                                   [task_params] * len(payloads)))
    elapsed = time.perf_counter() - started; stop.set(); sampler.join(timeout=1)
    return {"execution_time_seconds": elapsed,
            "cpu_percent": statistics.fmean(samples["cpu"]) if samples["cpu"] else 0.0,
            "memory_percent": statistics.fmean(samples["memory"]) if samples["memory"] else psutil.virtual_memory().percent,
            "completed_tasks": len(values), "failed_tasks": 0,
            "result": merge_results(values, args.operation), "task_distribution": {"local": len(values)},
            "recovery_time_seconds": None, "requeued": 0}


def api(session: requests.Session, method: str, url: str, **kwargs):
    response = session.request(method, url, timeout=kwargs.pop("timeout", 20), **kwargs)
    if not response.ok:
        raise RuntimeError(f"{method} {url}: HTTP {response.status_code} {response.text[:500]}")
    return response


def distributed_run(session: requests.Session, args, workers: int, scheduling: str,
                    inject_fault: bool = False, extra_params: dict[str, Any] | None = None) -> dict[str, Any]:
    api(session, "POST", args.master + "/reset")
    job = api(session, "POST", args.master + "/jobs", json={"operation": args.operation,
        "start_year": args.start_year, "end_year": args.end_year,
        "months_per_task": args.months_per_task, "worker_count": workers,
        "scheduling": scheduling, "params": {"payload_mode": "grid",
        "work_factor": args.work_factor, **(extra_params or {})}}).json()
    job_id = job["job_id"]; started = time.perf_counter(); fault_worker = None
    while True:
        status = api(session, "GET", args.master + "/status", params={"job_id": job_id}).json()
        counts = status["tasks"]; total = sum(counts.values())
        if inject_fault and fault_worker is None:
            running = [task for task in status.get("task_details", []) if task["status"] == "running"]
            if running:
                candidate = running[0]["assigned_worker"]
                response = session.post(f"{args.master}/fault/inject/{candidate}", timeout=10)
                if response.status_code == 202:
                    fault_worker = candidate
        if total and counts["completed"] + counts["failed"] == total:
            break
        if time.perf_counter() - started > args.timeout:
            raise TimeoutError(f"job {job_id} melewati {args.timeout} detik")
        time.sleep(args.poll_interval)
    elapsed = time.perf_counter() - started
    metrics = api(session, "GET", args.master + "/metrics").json()
    recovery = [event["recovery_seconds"] for event in status["recovery"]
                if event.get("recovery_seconds") is not None]
    return {"execution_time_seconds": elapsed, "cpu_percent": metrics["mean_cpu_percent"],
            "memory_percent": metrics["mean_memory_percent"],
            "recovery_time_seconds": max(recovery) if recovery else None,
            "completed_tasks": counts["completed"], "failed_tasks": counts["failed"],
            "task_distribution": status.get("task_distribution", {}),
            "requeued": metrics["requeued"], "job_id": job_id, "fault_worker": fault_worker,
            "result": status["aggregate"]}


def make_row(scenario: str, repetition: int, processors: int, scheduling: str,
             value: dict[str, Any], baseline: float) -> dict[str, Any]:
    elapsed = value["execution_time_seconds"]; speedup = baseline / elapsed
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "scenario": scenario,
        "repetition": repetition, "workers_or_processes": processors, "scheduling": scheduling,
        "execution_time_seconds": elapsed, "speedup": speedup,
        "efficiency": speedup / processors, "throughput_tasks_second": value["completed_tasks"] / elapsed,
        "cpu_percent": value.get("cpu_percent"), "memory_percent": value.get("memory_percent"),
        "recovery_time_seconds": value.get("recovery_time_seconds"), "requeued": value.get("requeued", 0),
        "completed_tasks": value["completed_tasks"], "failed_tasks": value.get("failed_tasks", 0),
        "task_distribution": json.dumps(value.get("task_distribution", {}), sort_keys=True),
        "job_id": value.get("job_id"), "fault_worker": value.get("fault_worker")}


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for scenario in dict.fromkeys(row["scenario"] for row in rows):
        group = [row for row in rows if row["scenario"] == scenario]
        summary: dict[str, Any] = {"scenario": scenario, "runs": len(group),
            "workers_or_processes": group[0]["workers_or_processes"],
            "scheduling": group[0]["scheduling"]}
        for key in ("execution_time_seconds", "speedup", "efficiency", "throughput_tasks_second",
                    "cpu_percent", "memory_percent", "recovery_time_seconds"):
            values = [float(row[key]) for row in group if row.get(key) is not None]
            summary[f"mean_{key}"] = statistics.fmean(values) if values else None
            summary[f"stdev_{key}"] = statistics.stdev(values) if len(values) > 1 else 0.0 if values else None
        summary["total_requeued"] = sum(int(row["requeued"]) for row in group)
        summary["total_failed"] = sum(int(row["failed_tasks"]) for row in group)
        output.append(summary)
    return output


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def write_analysis(path: Path, summaries: list[dict[str, Any]]) -> None:
    lines = ["# Analisis Otomatis Benchmark D-LUMEN", "",
             "Angka berikut berasal dari eksperimen nyata; verifikasi konteks jaringan dan beban perangkat.", ""]
    for row in summaries:
        lines.extend([f"## {row['scenario']}", "",
            f"- Pengulangan: {row['runs']}",
            f"- Execution time rata-rata: {row['mean_execution_time_seconds']:.6f} s",
            f"- Speedup rata-rata: {row['mean_speedup']:.4f}",
            f"- Efficiency rata-rata: {row['mean_efficiency'] * 100:.2f}%",
            f"- Throughput rata-rata: {row['mean_throughput_tasks_second']:.4f} task/s",
            f"- CPU rata-rata: {row['mean_cpu_percent']:.2f}%" if row['mean_cpu_percent'] is not None else "- CPU: tidak tersedia",
            f"- RAM rata-rata: {row['mean_memory_percent']:.2f}%" if row['mean_memory_percent'] is not None else "- RAM: tidak tersedia",
            f"- Recovery time: {row['mean_recovery_time_seconds']:.4f} s" if row['mean_recovery_time_seconds'] is not None else "- Recovery time: tidak berlaku",
            f"- Task gagal: {row['total_failed']}; requeue: {row['total_requeued']}", ""])
    by_name = {row["scenario"]: row for row in summaries}
    static = by_name.get("E4_load_balancing_static"); dynamic = by_name.get("E4_load_balancing_dynamic")
    if static and dynamic:
        improvement = ((static["mean_execution_time_seconds"] - dynamic["mean_execution_time_seconds"])
                       / static["mean_execution_time_seconds"] * 100)
        lines.extend(["## Perbandingan Load Balancing", "",
            f"Dynamic scheduling mengubah execution time sebesar {improvement:.2f}% dibanding static ",
            "(nilai positif berarti dynamic lebih cepat). Distribusi task pada raw CSV digunakan untuk ",
            "menjelaskan apakah Worker cepat mengambil task lebih banyak.", ""])
    scale = [row for row in summaries if row["scenario"].startswith("E6_scalability_")]
    if scale:
        fastest = min(scale, key=lambda row: row["mean_execution_time_seconds"])
        lines.extend(["## Analisis Scalability", "",
            f"Konfigurasi tercepat adalah {fastest['scenario']} dengan waktu rata-rata ",
            f"{fastest['mean_execution_time_seconds']:.6f} detik. Efficiency yang menurun saat Worker ",
            "bertambah menunjukkan overhead jaringan, serialisasi JSON, dan koordinasi Master.", ""])
    fault = by_name.get("E5_fault_tolerance")
    if fault:
        lines.extend(["## Analisis Fault Tolerance", "",
            f"Recovery time tercatat {fault['mean_recovery_time_seconds']} detik dengan ",
            f"{fault['total_requeued']} task di-requeue dan {fault['total_failed']} task gagal permanen.",
            "Eksperimen valid bila requeue > 0, recovery time tersedia, dan task gagal permanen = 0.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def plot(path: Path, summaries: list[dict[str, Any]]) -> None:
    try:
        import matplotlib.pyplot as chart
    except ImportError:
        print("Matplotlib tidak tersedia; grafik dilewati."); return
    labels = [row["scenario"] for row in summaries]
    figure, axes = chart.subplots(2, 2, figsize=(15, 9))
    series = (("mean_execution_time_seconds", "Execution time (s)"),
              ("mean_speedup", "Speedup"), ("mean_efficiency", "Efficiency"),
              ("mean_throughput_tasks_second", "Throughput (task/s)"))
    for axis, (key, title) in zip(axes.flat, series):
        axis.bar(range(len(labels)), [row[key] or 0 for row in summaries]); axis.set_title(title)
        axis.set_xticks(range(len(labels)), labels, rotation=70, ha="right", fontsize=7)
    figure.tight_layout(); figure.savefig(path, dpi=180); chart.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default=os.getenv("DLUMEN_MASTER_URL", "http://127.0.0.1:5050"))
    parser.add_argument("--start-year", type=int, default=2024); parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--operation", choices=["aggregate", "extreme", "growth"], default="aggregate")
    parser.add_argument("--months-per-task", type=int, default=1); parser.add_argument("--local-processes", default="2,4,8")
    parser.add_argument("--scalability", default="1,2,4,6,9"); parser.add_argument("--distributed-workers", type=int, default=9)
    parser.add_argument("--repetitions", type=int, default=3); parser.add_argument("--work-factor", type=int, default=100000)
    parser.add_argument("--timeout", type=float, default=3600); parser.add_argument("--poll-interval", type=float, default=.1)
    parser.add_argument("--output", default="benchmark/results/uas"); parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--skip-fault", action="store_true", help="Lewati E5 bila tidak ingin mematikan Worker")
    args = parser.parse_args(); args.master = args.master.rstrip("/")
    if args.repetitions < 1 or args.work_factor < 1: raise SystemExit("repetitions dan work-factor minimal 1")
    probe = ViirsRepository().payload({"start_year": args.start_year, "start_month": 1,
        "end_year": args.start_year, "end_month": 1, "payload_mode": "grid"})
    if probe.get("mode") != "grid" or len(probe["records"]) < 2:
        raise SystemExit("Grid PostgreSQL belum siap; jalankan database.init_db dan database.import_viirs")
    raw: list[dict[str, Any]] = []; sequential_values = []
    for repetition in range(1, args.repetitions + 1):
        value = local_run(1, args); sequential_values.append(value)
    baseline = statistics.fmean(v["execution_time_seconds"] for v in sequential_values)
    raw.extend(make_row("E1_sequential", i, 1, "local", value, baseline)
               for i, value in enumerate(sequential_values, 1))
    for processes in map(int, args.local_processes.split(",")):
        for repetition in range(1, args.repetitions + 1):
            raw.append(make_row(f"E2_local_{processes}_processes", repetition, processes, "local",
                                local_run(processes, args), baseline))
    if not args.local_only:
        session = requests.Session(); token = os.getenv("DLUMEN_TOKEN", "")
        if token: session.headers["X-DLUMEN-Token"] = token
        online = [worker for worker in api(session, "GET", args.master + "/metrics").json()["workers"] if worker["online"]]
        required = max(map(int, args.scalability.split(",")))
        if len(online) < required:
            raise SystemExit(f"Butuh {required} Worker online; tersedia {len(online)}")
        for repetition in range(1, args.repetitions + 1):
            raw.append(make_row("E3_distributed_9", repetition, args.distributed_workers, "dynamic",
                distributed_run(session, args, args.distributed_workers, "dynamic"), baseline))
        for scheduling in ("static", "dynamic"):
            for repetition in range(1, args.repetitions + 1):
                raw.append(make_row(f"E4_load_balancing_{scheduling}", repetition,
                    args.distributed_workers, scheduling,
                    distributed_run(session, args, args.distributed_workers, scheduling), baseline))
        for count in map(int, args.scalability.split(",")):
            for repetition in range(1, args.repetitions + 1):
                raw.append(make_row(f"E6_scalability_{count}_workers", repetition, count, "dynamic",
                    distributed_run(session, args, count, "dynamic"), baseline))
        if not args.skip_fault:
            fault_params = {"minimum_chunk_seconds": 5}
            raw.append(make_row("E5_no_failure", 1, args.distributed_workers, "dynamic",
                distributed_run(session, args, args.distributed_workers, "dynamic",
                                extra_params=fault_params), baseline))
            raw.append(make_row("E5_fault_tolerance", 1, args.distributed_workers, "dynamic",
                distributed_run(session, args, args.distributed_workers, "dynamic", inject_fault=True,
                                extra_params=fault_params), baseline))
    summary = summarize(raw); base = Path(args.output)
    write_table(base.with_name(base.name + "_raw"), raw)
    write_table(base.with_name(base.name + "_summary"), summary)
    write_analysis(base.with_name(base.name + "_analysis.md"), summary)
    plot(base.with_name(base.name + "_charts.png"), summary)
    print(json.dumps(summary, indent=2))
    print(f"Hasil: {base.parent.resolve()}")


if __name__ == "__main__":
    main()
