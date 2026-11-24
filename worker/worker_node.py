"""Portable worker requiring only requests, numpy and psutil."""
from __future__ import annotations

import os
import socket
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


def compute_chunk(operation: str, records: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    if not records:
        return {"months": 0, "valid_pixels": 0, "sum_radiance": 0.0,
                "min_radiance": None, "max_radiance": None}
    pixels = np.asarray([row["valid_pixels"] for row in records], dtype=np.int64)
    totals = np.asarray([row["sum_radiance"] for row in records], dtype=np.float64)
    means = np.asarray([row["mean_radiance"] for row in records], dtype=np.float64)
    result: dict[str, Any] = {"months": len(records), "valid_pixels": int(pixels.sum()),
        "sum_radiance": float(totals.sum()), "min_radiance": float(min(r["min_radiance"] for r in records)),
        "max_radiance": float(max(r["max_radiance"] for r in records))}
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
    return result


def split_records(records: list[dict[str, Any]], count: int) -> list[list[dict[str, Any]]]:
    return [part.tolist() for part in np.array_split(np.asarray(records, dtype=object), min(count, len(records)))] if records else [[]]


def merge_results(parts: list[dict[str, Any]], operation: str) -> dict[str, Any]:
    pixels = sum(x["valid_pixels"] for x in parts); total = sum(x["sum_radiance"] for x in parts)
    lows = [x["min_radiance"] for x in parts if x["min_radiance"] is not None]
    highs = [x["max_radiance"] for x in parts if x["max_radiance"] is not None]
    result = {"months": sum(x["months"] for x in parts), "valid_pixels": pixels,
              "sum_radiance": total, "global_mean": total / pixels if pixels else None,
              "min_radiance": min(lows) if lows else None, "max_radiance": max(highs) if highs else None}
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
    session = requests.Session(); session.headers.update(HEADERS)
    session.post(MASTER_URL + "/register", json={"worker_id": WORKER_ID,
        "hostname": socket.gethostname(), "processes": PROCESSES, "platform": os.name}, timeout=10).raise_for_status()
    with ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        while True:
            try:
                session.post(MASTER_URL + "/heartbeat", json={"worker_id": WORKER_ID,
                    "metrics": metrics()}, timeout=10).raise_for_status()
                response = session.get(f"{MASTER_URL}/get-task/{WORKER_ID}", timeout=20)
                if response.status_code == 204:
                    time.sleep(1); continue
                response.raise_for_status(); task = response.json()["task"]
                started = time.perf_counter(); records = task["payload"]["records"]
                futures = [pool.submit(compute_chunk, task["operation"], chunk, task["params"])
                           for chunk in split_records(records, PROCESSES)]
                result = merge_results([future.result() for future in futures], task["operation"])
                sample = metrics(); sample["execution_seconds"] = time.perf_counter() - started
                session.post(MASTER_URL + "/submit-result", json={"worker_id": WORKER_ID,
                    "task_id": task["task_id"], "result": result, "metrics": sample}, timeout=20).raise_for_status()
            except KeyboardInterrupt:
                break
            except Exception as exc:
                if "task" in locals():
                    try: session.post(MASTER_URL + "/task-failed", json={"worker_id": WORKER_ID,
                        "task_id": task["task_id"], "error": f"{type(exc).__name__}: {exc}"}, timeout=5)
                    except requests.RequestException: pass
                time.sleep(2)


if __name__ == "__main__":
    main()
