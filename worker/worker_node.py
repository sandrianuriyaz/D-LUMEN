"""Portable worker requiring only requests, numpy and psutil."""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np
import psutil
import requests

MASTER_URL = os.getenv("DLUMEN_MASTER_URL", "http://127.0.0.1:5050").rstrip("/")
WORKER_ID = os.getenv("DLUMEN_WORKER_ID", f"{socket.gethostname()}-{uuid.getnode():x}")
PROCESSES = max(1, int(os.getenv("DLUMEN_PROCESSES") or (os.cpu_count() or 1)))
TOKEN = os.getenv("DLUMEN_TOKEN", "")
HEADERS = {"X-DLUMEN-Token": TOKEN} if TOKEN else {}


def configure_logging() -> logging.Logger:
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("dlumen.worker")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(); console.setFormatter(formatter)
    file_handler = logging.FileHandler(os.path.join(log_dir, f"worker-{WORKER_ID}.log"), encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(console); logger.addHandler(file_handler)
    return logger


def print_banner(log_file: str) -> None:
    print("=" * 62, flush=True)
    print(" D-LUMEN — Distributed Light Pollution Monitoring", flush=True)
    print(" Worker tanpa PostgreSQL (HTTP/REST + multiprocessing)", flush=True)
    print(f" Worker ID : {WORKER_ID}", flush=True)
    print(f" Master    : {MASTER_URL}", flush=True)
    print(f" Proses    : {PROCESSES} core", flush=True)
    print(f" Log       : {log_file}", flush=True)
    print(" Tekan Ctrl+C untuk berhenti.", flush=True)
    print("=" * 62, flush=True)


def compute_chunk(operation: str, records: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    chunk_started = time.perf_counter()
    if not records:
        return {"months": 0, "valid_pixels": 0, "sum_radiance": 0.0,
                "min_radiance": None, "max_radiance": None}
    pixels = np.asarray([row["valid_pixels"] for row in records], dtype=np.int64)
    totals = np.asarray([row["sum_radiance"] for row in records], dtype=np.float64)
    means = np.asarray([row["mean_radiance"] for row in records], dtype=np.float64)
    periods = sorted({f'{int(row["year"]):04d}-{int(row["month"]):02d}' for row in records})
    # Repeat a deterministic numerical kernel to create a controlled, comparable
    # CPU workload without changing the scientific aggregate.
    checksum = 0.0
    for index in range(max(1, int(params.get("work_factor", 1)))):
        scale = 1.0 + (index % 97) * 1e-6
        checksum += float(np.sin(means * scale).sum() + np.sqrt(np.abs(means) + scale).sum())
    result: dict[str, Any] = {"months": len(periods), "periods": periods,
        "valid_pixels": int(pixels.sum()),
        "sum_radiance": float(totals.sum()), "min_radiance": float(min(r["min_radiance"] for r in records)),
        "max_radiance": float(max(r["max_radiance"] for r in records)), "work_checksum": checksum}
    if operation == "extreme":
        threshold = float(params.get("threshold", 50.0))
        result["extreme_records"] = [row for row, mean in zip(records, means) if mean >= threshold]
    elif operation == "growth":
        annual: dict[int, list[float]] = {}
        for row, mean in zip(records, means):
            annual.setdefault(int(row["year"]), []).append(float(mean))
        averages = {year: float(np.mean(values)) for year, values in annual.items()}
        years = sorted(averages)
        result["annual_mean"] = averages
        result["growth_percent"] = ({str(year): (averages[year] - averages[years[i-1]]) /
            averages[years[i-1]] * 100 if averages[years[i-1]] else None
            for i, year in enumerate(years) if i} if len(years) > 1 else {})
    minimum = float(params.get("minimum_chunk_seconds", 0))
    remaining = minimum - (time.perf_counter() - chunk_started)
    if remaining > 0:
        time.sleep(remaining)
    return result


def split_records(records: list[dict[str, Any]], count: int) -> list[list[dict[str, Any]]]:
    return [part.tolist() for part in np.array_split(np.asarray(records, dtype=object), min(count, len(records)))] if records else [[]]


def merge_results(parts: list[dict[str, Any]], operation: str) -> dict[str, Any]:
    pixels = sum(x["valid_pixels"] for x in parts); total = sum(x["sum_radiance"] for x in parts)
    lows = [x["min_radiance"] for x in parts if x["min_radiance"] is not None]
    highs = [x["max_radiance"] for x in parts if x["max_radiance"] is not None]
    periods = sorted({period for part in parts for period in part.get("periods", [])})
    result = {"months": len(periods) if periods else sum(x["months"] for x in parts),
              "periods": periods, "valid_pixels": pixels,
              "sum_radiance": total, "global_mean": total / pixels if pixels else None,
              "min_radiance": min(lows) if lows else None, "max_radiance": max(highs) if highs else None,
              "work_checksum": sum(x.get("work_checksum", 0.0) for x in parts)}
    if operation == "extreme": result["extreme_records"] = sum((x.get("extreme_records", []) for x in parts), [])
    if operation == "growth":
        annual = {}; [annual.update(x.get("annual_mean", {})) for x in parts]
        years = sorted(annual, key=int); result["annual_mean"] = annual
        result["growth_percent"] = {str(year): (annual[year]-annual[years[i-1]])/annual[years[i-1]]*100
            if annual[years[i-1]] else None for i, year in enumerate(years) if i}
    return result


def metrics() -> dict[str, float]:
    return {"cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent}


def main() -> None:
    logger = configure_logging()
    log_file = os.path.abspath(os.path.join("logs", f"worker-{WORKER_ID}.log"))
    print_banner(log_file)
    session = requests.Session(); session.headers.update(HEADERS)
    registered = False; waiting_logged_at = 0.0; task = None
    stop_heartbeat = threading.Event()

    def heartbeat_loop() -> None:
        heartbeat_session = requests.Session(); heartbeat_session.headers.update(HEADERS)
        while not stop_heartbeat.wait(1):
            if not registered:
                continue
            try:
                response = heartbeat_session.post(MASTER_URL + "/heartbeat", json={"worker_id": WORKER_ID,
                    "metrics": metrics()}, timeout=5)
                response.raise_for_status()
                if response.json().get("command") == "terminate":
                    logger.error("FAULT INJECTION diterima; Worker dihentikan sekarang")
                    os._exit(73)
            except requests.RequestException as exc:
                logger.warning("Heartbeat gagal: %s", exc)

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    with ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        while True:
            try:
                if not registered:
                    logger.info("Menghubungkan ke Master %s ...", MASTER_URL)
                    response = session.post(MASTER_URL + "/register", json={"worker_id": WORKER_ID,
                        "hostname": socket.gethostname(), "processes": PROCESSES,
                        "platform": os.name}, timeout=10)
                    response.raise_for_status(); registered = True
                    logger.info("WORKER ONLINE: %s berhasil terdaftar", WORKER_ID)
                response = session.get(f"{MASTER_URL}/get-task/{WORKER_ID}", timeout=20)
                if response.status_code == 204:
                    if time.monotonic() - waiting_logged_at >= 10:
                        logger.info("Menunggu task dari Master ...")
                        waiting_logged_at = time.monotonic()
                    time.sleep(1); continue
                response.raise_for_status(); task = response.json()["task"]
                logger.info("TASK DITERIMA: %s | partisi=%s | operasi=%s",
                            task["task_id"][:8], task["partition_id"], task["operation"])
                started = time.perf_counter(); records = task["payload"]["records"]
                futures = [pool.submit(compute_chunk, task["operation"], chunk, task["params"])
                           for chunk in split_records(records, PROCESSES)]
                result = merge_results([future.result() for future in futures], task["operation"])
                sample = metrics(); sample["execution_seconds"] = time.perf_counter() - started
                session.post(MASTER_URL + "/submit-result", json={"worker_id": WORKER_ID,
                    "task_id": task["task_id"], "result": result, "metrics": sample}, timeout=20).raise_for_status()
                logger.info("TASK SELESAI: %s | %.3f detik | %s record | CPU %.1f%% | RAM %.1f%%",
                            task["task_id"][:8], sample["execution_seconds"], len(records),
                            sample["cpu_percent"], sample["memory_percent"])
                task = None
            except KeyboardInterrupt:
                logger.info("Worker %s dihentikan oleh pengguna", WORKER_ID)
                stop_heartbeat.set()
                break
            except requests.RequestException as exc:
                registered = False
                logger.warning("Koneksi Master gagal: %s. Mencoba lagi dalam 3 detik ...", exc)
                time.sleep(3)
            except Exception as exc:
                logger.exception("TASK GAGAL: %s", exc)
                if task:
                    try: session.post(MASTER_URL + "/task-failed", json={"worker_id": WORKER_ID,
                        "task_id": task["task_id"], "error": f"{type(exc).__name__}: {exc}"}, timeout=5)
                    except requests.RequestException: pass
                    task = None
                time.sleep(2)


if __name__ == "__main__":
    main()
