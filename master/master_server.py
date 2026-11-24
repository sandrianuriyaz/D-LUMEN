"""Central REST master: task decomposition, payload delivery and recovery."""
from __future__ import annotations

import os
import threading
import time
import uuid
from functools import wraps
from typing import Any

from flask import Flask, jsonify, request

from master.repository import ViirsRepository
from parallel.core import TaskStore, WorkerRegistry, aggregate_results, make_tasks

TOKEN = os.getenv("DLUMEN_TOKEN", "")
PORT = int(os.getenv("DLUMEN_MASTER_PORT", "5050"))
TASK_TIMEOUT = float(os.getenv("DLUMEN_TASK_TIMEOUT", "15"))
HEARTBEAT_TIMEOUT = float(os.getenv("DLUMEN_HEARTBEAT_TIMEOUT", "15"))

app = Flask(__name__)
store = TaskStore(int(os.getenv("DLUMEN_MAX_RETRIES", "2")))
registry = WorkerRegistry(HEARTBEAT_TIMEOUT)
repository = ViirsRepository()
jobs: dict[str, dict[str, Any]] = {}
metrics_state = {"started_at": time.time(), "assignments": 0, "completed": 0,
                 "requeued": 0, "worker_samples": []}


def protected(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if TOKEN and request.headers.get("X-DLUMEN-Token") != TOKEN:
            return jsonify(error="unauthorized"), 401
        return function(*args, **kwargs)
    return wrapper


@app.get("/health")
def health():
    return jsonify(status="online", role="master", database="central")


@app.post("/register")
@app.post("/api/register")
@protected
def register():
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id", "")).strip()
    if not worker_id:
        return jsonify(error="worker_id wajib diisi"), 400
    registry.register(worker_id, request.remote_addr or "unknown", data)
    return jsonify(status="registered", task_timeout_seconds=TASK_TIMEOUT)


@app.post("/heartbeat")
@app.post("/api/heartbeat")
@protected
def heartbeat():
    data = request.get_json(silent=True) or {}
    worker_id = str(data.get("worker_id", ""))
    sample = data.get("metrics", {})
    if not registry.heartbeat(worker_id, sample):
        return jsonify(status="register_required"), 404
    metrics_state["worker_samples"].append({"at": time.time(), "worker_id": worker_id, **sample})
    metrics_state["worker_samples"] = metrics_state["worker_samples"][-10000:]
    return jsonify(status="ok")


@app.post("/jobs")
@app.post("/api/jobs")
@protected
def create_job():
    data = request.get_json(silent=True) or {}
    operation = data.get("operation", "aggregate")
    if operation not in {"aggregate", "extreme", "growth"}:
        return jsonify(error="operation harus aggregate, extreme, atau growth"), 400
    start_year, end_year = int(data.get("start_year", 2020)), int(data.get("end_year", 2025))
    if start_year > end_year:
        return jsonify(error="start_year tidak boleh melebihi end_year"), 400
    active = sorted((w for w in registry.snapshot() if w["online"]), key=lambda w: w["id"])
    requested_workers = int(data.get("worker_count", len(active)))
    if not 1 <= requested_workers <= 9:
        return jsonify(error="worker_count harus 1 sampai 9"), 400
    selected = [w["id"] for w in active[:requested_workers]]
    if not selected:
        return jsonify(error="minimal satu Worker aktif diperlukan"), 409
    scheduling = data.get("scheduling", "dynamic")
    if scheduling not in {"dynamic", "static"}:
        return jsonify(error="scheduling harus dynamic atau static"), 400
    job_id = str(uuid.uuid4())
    tasks = make_tasks(operation, start_year, end_year, int(data.get("months_per_task", 1)),
                       params=data.get("params", {}), job_id=job_id)
    for index, task in enumerate(tasks):
        task.eligible_workers = selected
        if scheduling == "static":
            task.params["_static_worker"] = selected[index % len(selected)]
    store.add(tasks)
    jobs[job_id] = {"job_id": job_id, "operation": operation, "created_at": time.time(),
                    "task_count": len(tasks), "start_year": start_year, "end_year": end_year,
                    "scheduling": scheduling, "worker_ids": selected}
    return jsonify(job_id=job_id, count=len(tasks), worker_ids=selected,
                   task_ids=[task.task_id for task in tasks]), 201


@app.get("/get-task/<worker_id>")
@protected
def get_task(worker_id: str):
    if worker_id not in registry.workers:
        return jsonify(error="worker belum terdaftar"), 404
    task = store.claim(worker_id)
    if task is None:
        return jsonify(task=None), 204
    try:
        payload = repository.payload(task.params)
    except Exception as exc:
        store.fail(task.task_id, f"payload error: {exc}")
        return jsonify(error="Master gagal menyiapkan payload", detail=str(exc)), 503
    metrics_state["assignments"] += 1
    public = task.public()
    public["payload"] = payload
    public["lease_seconds"] = TASK_TIMEOUT
    return jsonify(task=public)


@app.post("/submit-result")
@protected
def submit_result():
    data = request.get_json(silent=True) or {}
    accepted = store.complete(str(data.get("task_id", "")), str(data.get("worker_id", "")),
                              data.get("result", {}))
    if accepted:
        metrics_state["completed"] += 1
        sample = data.get("metrics", {})
        metrics_state["worker_samples"].append({"at": time.time(),
            "worker_id": data.get("worker_id"), **sample})
    return jsonify(accepted=accepted), 200 if accepted else 409


@app.post("/task-failed")
@protected
def task_failed():
    data = request.get_json(silent=True) or {}
    task_id = str(data.get("task_id", ""))
    if task_id not in store.tasks:
        return jsonify(error="task tidak ditemukan"), 404
    store.fail(task_id, str(data.get("error", "worker error")))
    return jsonify(status=store.tasks[task_id].status.value)


def _status(job_id: str | None = None) -> dict[str, Any]:
    counts = store.counts(job_id)
    results = store.job_results(job_id) if job_id else list(store.results.values())
    total = sum(counts.values())
    return {"job": jobs.get(job_id), "tasks": counts,
            "progress": counts["completed"] / total * 100 if total else 0,
            "aggregate": aggregate_results(results), "results": results,
            "recovery": store.recovery_events(job_id), "workers": registry.snapshot()}


@app.get("/status")
@app.get("/api/status")
def status():
    return jsonify(_status(request.args.get("job_id")))


@app.get("/metrics")
def metrics():
    samples = metrics_state["worker_samples"]
    cpu = [float(x["cpu_percent"]) for x in samples if isinstance(x.get("cpu_percent"), (int, float))]
    memory = [float(x["memory_percent"]) for x in samples if isinstance(x.get("memory_percent"), (int, float))]
    recovery = [x["recovery_seconds"] for x in store.recovery_events() if x["recovery_seconds"] is not None]
    return jsonify(uptime_seconds=time.time() - metrics_state["started_at"],
        assignments=metrics_state["assignments"], completed=metrics_state["completed"],
        requeued=metrics_state["requeued"], mean_cpu_percent=sum(cpu)/len(cpu) if cpu else None,
        mean_memory_percent=sum(memory)/len(memory) if memory else None,
        recovery_time_seconds=max(recovery) if recovery else None, workers=registry.snapshot(),
        tasks=store.counts())


@app.post("/reset")
@protected
def reset():
    with store.lock:
        store.tasks.clear(); store.results.clear()
    jobs.clear()
    metrics_state.update(started_at=time.time(), assignments=0, completed=0, requeued=0,
                         worker_samples=[])
    return jsonify(status="reset", workers_preserved=len(registry.workers))


def monitor(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    while not stop.wait(1):
        for worker_id in registry.refresh():
            metrics_state["requeued"] += len(store.recover_worker(worker_id))
        metrics_state["requeued"] += len(store.expire(TASK_TIMEOUT))


def main() -> None:
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
