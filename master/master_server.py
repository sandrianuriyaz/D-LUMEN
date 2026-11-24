"""Central REST master: task decomposition, payload delivery and recovery."""
from __future__ import annotations

import os
import logging
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
failure_injections: set[str] = set()


def configure_logging() -> logging.Logger:
    log_dir = os.path.join(os.getcwd(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("dlumen.master")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(); console.setFormatter(formatter)
    file_handler = logging.FileHandler(os.path.join(log_dir, "master.log"), encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(console); logger.addHandler(file_handler)
    return logger


logger = configure_logging()


def print_banner() -> None:
    print("=" * 66, flush=True)
    print(" D-LUMEN — CENTRAL MASTER", flush=True)
    print(" PostgreSQL terpusat + REST dynamic work-pulling", flush=True)
    print(f" Port      : {PORT}", flush=True)
    print(f" Worker    : 0/9 online", flush=True)
    print(f" Metrics   : http://127.0.0.1:{PORT}/metrics", flush=True)
    print(f" Log       : {os.path.abspath(os.path.join('logs', 'master.log'))}", flush=True)
    print(" Tekan Ctrl+C untuk berhenti.", flush=True)
    print("=" * 66, flush=True)


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
    was_known = worker_id in registry.workers and registry.workers[worker_id].get("online", False)
    registry.register(worker_id, request.remote_addr or "unknown", data)
    online = sum(worker["online"] for worker in registry.snapshot())
    logger.info("WORKER %s: %s | IP=%s | proses=%s | online=%s/9",
                "TERDAFTAR ULANG" if was_known else "ONLINE", worker_id,
                request.remote_addr or "unknown", data.get("processes", "?"), online)
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
    command = None
    if worker_id in failure_injections:
        failure_injections.discard(worker_id); command = "terminate"
        logger.warning("FAULT INJECTION dikirim ke Worker %s", worker_id)
    return jsonify(status="ok", command=command)


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
    logger.info("JOB DIBUAT: %s | operasi=%s | task=%s | worker=%s | mode=%s",
                job_id[:8], operation, len(tasks), ",".join(selected), scheduling)
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
        task = store.tasks[str(data.get("task_id"))]
        counts = store.counts(task.job_id); total = sum(counts.values())
        logger.info("TASK SELESAI: %s | worker=%s | progres=%s/%s (%.1f%%)",
                    task.task_id[:8], data.get("worker_id"), counts["completed"], total,
                    counts["completed"] / total * 100 if total else 0)
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
    details = [task.public() for task in store.tasks.values()
               if job_id is None or task.job_id == job_id]
    assignments: dict[str, int] = {}
    for task in details:
        if task.get("assigned_worker"):
            assignments[task["assigned_worker"]] = assignments.get(task["assigned_worker"], 0) + 1
    finished = [task["finished_at"] for task in details if task.get("finished_at")]
    job = jobs.get(job_id)
    execution = (max(finished) - job["created_at"] if job and len(finished) == len(details) and details else None)
    return {"job": job, "tasks": counts, "task_details": details,
            "task_distribution": assignments, "execution_time_seconds": execution,
            "progress": counts["completed"] / total * 100 if total else 0,
            "aggregate": aggregate_results(results), "results": results,
            "recovery": store.recovery_events(job_id), "workers": registry.snapshot()}


@app.post("/fault/inject/<worker_id>")
@protected
def inject_fault(worker_id: str):
    worker = registry.workers.get(worker_id)
    if not worker or not worker.get("online"):
        return jsonify(error="Worker tidak online"), 404
    running = [task.task_id for task in store.tasks.values()
               if task.status.value == "running" and task.assigned_worker == worker_id]
    if not running:
        return jsonify(error="Worker tidak sedang mengerjakan task"), 409
    failure_injections.add(worker_id)
    return jsonify(status="scheduled", worker_id=worker_id, running_tasks=running), 202


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
    failure_injections.clear()
    metrics_state.update(started_at=time.time(), assignments=0, completed=0, requeued=0,
                         worker_samples=[])
    logger.info("RESET: antrean task dan metrik dikosongkan; registry Worker dipertahankan")
    return jsonify(status="reset", workers_preserved=len(registry.workers))


def monitor(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    while not stop.wait(1):
        for worker_id in registry.refresh():
            recovered = store.recover_worker(worker_id)
            metrics_state["requeued"] += len(recovered)
            online = sum(worker["online"] for worker in registry.snapshot())
            logger.warning("WORKER OFFLINE: %s | online=%s/9 | task dikembalikan=%s",
                           worker_id, online, len(recovered))
        expired = store.expire(TASK_TIMEOUT)
        metrics_state["requeued"] += len(expired)
        if expired:
            logger.warning("TIMEOUT: %s task dikembalikan ke antrean", len(expired))


def main() -> None:
    print_banner()
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
