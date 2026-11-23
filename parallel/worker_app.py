from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor

import requests
from flask import Flask, jsonify, request

from parallel.db import execute_operation
from parallel.raster_workload import analyze_raster

TOKEN = os.getenv("DLUMEN_TOKEN", "")
WORKER_ID = os.getenv("DLUMEN_WORKER_ID", f"{socket.gethostname()}-{uuid.getnode():x}")
WORKER_PORT = int(os.getenv("DLUMEN_WORKER_PORT", "5002"))
DISCOVERY_PORT = int(os.getenv("DLUMEN_DISCOVERY_PORT", "5005"))
PROCESSES = max(1, int(os.getenv("DLUMEN_PROCESSES", str(os.cpu_count() or 1))))
PARTITIONS = {p for p in os.getenv("DLUMEN_PARTITIONS", "").split(",") if p}
MASTER_URL = os.getenv("DLUMEN_MASTER_URL", "").rstrip("/")
HEADERS = {"X-DLUMEN-Token": TOKEN}
app = Flask(__name__)
state = {"master": MASTER_URL or None, "registered": False, "active": 0, "completed": 0}


def resource_metrics() -> dict:
    try:
        import psutil
        return {"cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent,
                "active_tasks": state["active"], "completed_tasks": state["completed"]}
    except ImportError:
        return {"cpu_percent": None, "memory_percent": None, "active_tasks": state["active"],
                "completed_tasks": state["completed"], "metrics_note": "install psutil"}


def discover(timeout=5) -> str | None:
    if MASTER_URL: return MASTER_URL
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", DISCOVERY_PORT)); sock.settimeout(timeout)
        try:
            payload, address = sock.recvfrom(256)
            prefix, port = payload.decode().split("|", 1)
            return f"http://{address[0]}:{int(port)}" if prefix == "DLUMEN_MASTER_V2" else None
        except (OSError, ValueError): return None


def register(master: str) -> bool:
    payload = {"worker_id": WORKER_ID, "name": socket.gethostname(), "port": WORKER_PORT,
               "processes": PROCESSES, "partitions": sorted(PARTITIONS), "platform": os.name}
    response = requests.post(master+"/api/register", json=payload, headers=HEADERS, timeout=10)
    response.raise_for_status(); return True


def execute_task(task: dict) -> dict:
    if task["operation"] == "raster_aggregate":
        return analyze_raster(task["params"])
    return execute_operation(task["operation"], task["params"])


def service_loop(stop: threading.Event | None = None):
    stop = stop or threading.Event()
    with ProcessPoolExecutor(max_workers=PROCESSES) as pool:
        futures = {}
        last_heartbeat = 0.0
        while not stop.wait(0.25):
            master = state.get("master") or discover()
            if not master: continue
            state["master"] = master
            try:
                if not state["registered"]:
                    state["registered"] = register(master)
                if time.time() - last_heartbeat >= 5:
                    requests.post(master+"/api/heartbeat", headers=HEADERS, timeout=5,
                                  json={"worker_id": WORKER_ID, "metrics": resource_metrics()}).raise_for_status()
                    last_heartbeat = time.time()
                while len(futures) < PROCESSES:
                    response = requests.post(master+"/api/tasks/claim", headers=HEADERS, timeout=10,
                        json={"worker_id": WORKER_ID, "partitions": sorted(PARTITIONS)})
                    if response.status_code == 204: break
                    response.raise_for_status(); task = response.json()["task"]
                    futures[pool.submit(execute_task, task)] = task
                state["active"] = len(futures)
                for future, task in list(futures.items()):
                    if not future.done(): continue
                    del futures[future]; state["active"] = len(futures)
                    try:
                        value = future.result()
                        requests.post(master+f"/api/tasks/{task['task_id']}/result", headers=HEADERS,
                            json={"worker_id": WORKER_ID, "result": value}, timeout=10).raise_for_status()
                        state["completed"] += 1
                    except Exception as exc:
                        requests.post(master+f"/api/tasks/{task['task_id']}/fail", headers=HEADERS,
                            json={"worker_id": WORKER_ID, "error": f"{type(exc).__name__}: {exc}"}, timeout=10)
            except requests.RequestException:
                state.update(master=None if not MASTER_URL else MASTER_URL, registered=False)
                stop.wait(3)


@app.get("/health")
def health():
    return jsonify(worker_id=WORKER_ID, status="online", master=state["master"], metrics=resource_metrics())


@app.get("/aggregate")
def legacy_aggregate():
    if TOKEN and __import__("flask").request.headers.get("X-DLUMEN-Token") != TOKEN:
        return jsonify(error="unauthorized"), 401
    return jsonify(worker=WORKER_ID, **execute_operation("aggregate", {}))


@app.post("/control/stop")
def controlled_stop():
    """Authenticated failure injection for a repeatable UAS recovery demo."""
    if not TOKEN or request.headers.get("X-DLUMEN-Token") != TOKEN:
        return jsonify(error="unauthorized"), 401
    delay = max(0.1, min(float((request.get_json(silent=True) or {}).get("delay", 0.5)), 5.0))
    def stop_process():
        time.sleep(delay)
        os._exit(73)
    threading.Thread(target=stop_process, daemon=True).start()
    return jsonify(status="stopping", worker_id=WORKER_ID, delay=delay), 202


def main():
    if not TOKEN: raise SystemExit("DLUMEN_TOKEN wajib diatur")
    threading.Thread(target=service_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=WORKER_PORT, threaded=True)


if __name__ == "__main__":
    main()
