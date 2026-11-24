from __future__ import annotations

import hashlib
import fnmatch
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Task:
    operation: str
    params: dict[str, Any]
    partition_id: str
    eligible_workers: list[str] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    assigned_worker: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    job_id: str = "default"
    recovery_started_at: float | None = None
    recovery_seconds: float | None = None

    def public(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


def make_tasks(operation: str, start_year: int, end_year: int,
               months_per_task: int = 1, replicas: dict[str, list[str]] | None = None,
               params: dict[str, Any] | None = None, job_id: str = "default") -> list[Task]:
    """Create unique, non-overlapping time partitions."""
    if months_per_task < 1:
        raise ValueError("months_per_task must be >= 1")
    periods = [(y, m) for y in range(start_year, end_year + 1) for m in range(1, 13)]
    tasks = []
    for offset in range(0, len(periods), months_per_task):
        chunk = periods[offset:offset + months_per_task]
        first, last = chunk[0], chunk[-1]
        partition = f"{first[0]:04d}-{first[1]:02d}_{last[0]:04d}-{last[1]:02d}"
        task_params = dict(params or {})
        task_params.update({"start_year": first[0], "start_month": first[1],
                            "end_year": last[0], "end_month": last[1]})
        tasks.append(Task(operation, task_params, partition,
                          list((replicas or {}).get(partition, [])), job_id=job_id))
    return tasks


class TaskStore:
    """Thread-safe queue with idempotent results and bounded retry."""
    def __init__(self, max_retries: int = 2):
        self.tasks: dict[str, Task] = {}
        self.results: dict[str, dict[str, Any]] = {}
        self.max_retries = max_retries
        self.lock = threading.RLock()

    def add(self, tasks: Iterable[Task]) -> None:
        with self.lock:
            for task in tasks:
                self.tasks.setdefault(task.task_id, task)

    def claim(self, worker_id: str, available_partitions: set[str] | None = None) -> Task | None:
        with self.lock:
            candidates = sorted(self.tasks.values(), key=lambda t: (t.attempts, t.created_at))
            for task in candidates:
                allowed = not task.eligible_workers or worker_id in task.eligible_workers
                preferred = task.params.get("_static_worker")
                if preferred and task.attempts == 0:
                    allowed = allowed and worker_id == preferred
                available = available_partitions is None or any(
                    fnmatch.fnmatch(task.partition_id, pattern) or task.partition_id.startswith(pattern)
                    for pattern in available_partitions)
                if task.status in (TaskStatus.PENDING, TaskStatus.RETRYING) and allowed and available:
                    task.status, task.assigned_worker = TaskStatus.RUNNING, worker_id
                    task.started_at, task.attempts, task.error = time.time(), task.attempts + 1, None
                    return task
        return None

    def complete(self, task_id: str, worker_id: str, result: dict[str, Any]) -> bool:
        with self.lock:
            task = self.tasks.get(task_id)
            if not task or task_id in self.results:
                return False
            if task.status != TaskStatus.RUNNING or task.assigned_worker != worker_id:
                return False
            self.results[task_id] = result
            task.status, task.finished_at = TaskStatus.COMPLETED, time.time()
            if task.recovery_started_at is not None:
                task.recovery_seconds = task.finished_at - task.recovery_started_at
            return True

    def fail(self, task_id: str, error: str) -> None:
        with self.lock:
            task = self.tasks[task_id]
            task.error, task.assigned_worker = error, None
            task.status = TaskStatus.RETRYING if task.attempts <= self.max_retries else TaskStatus.FAILED
            if task.status == TaskStatus.FAILED:
                task.finished_at = time.time()

    def recover_worker(self, worker_id: str, reason: str = "worker offline") -> list[str]:
        recovered = []
        with self.lock:
            for task in self.tasks.values():
                if task.status == TaskStatus.RUNNING and task.assigned_worker == worker_id:
                    task.recovery_started_at = time.time()
                    self.fail(task.task_id, reason)
                    recovered.append(task.task_id)
        return recovered

    def expire(self, timeout: float) -> list[str]:
        now = time.time()
        expired = []
        with self.lock:
            for task in self.tasks.values():
                if task.status == TaskStatus.RUNNING and task.started_at and now-task.started_at > timeout:
                    task.recovery_started_at = now
                    self.fail(task.task_id, "task timeout")
                    expired.append(task.task_id)
        return expired

    def counts(self, job_id: str | None = None) -> dict[str, int]:
        with self.lock:
            tasks = [t for t in self.tasks.values() if job_id is None or t.job_id == job_id]
            return {s.value: sum(t.status == s for t in tasks) for s in TaskStatus}

    def job_results(self, job_id: str) -> list[dict[str, Any]]:
        with self.lock:
            return [self.results[t.task_id] for t in self.tasks.values()
                    if t.job_id == job_id and t.task_id in self.results]

    def recovery_events(self, job_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            return [{"task_id": t.task_id, "partition_id": t.partition_id,
                     "attempts": t.attempts, "recovery_seconds": t.recovery_seconds,
                     "status": t.status.value, "worker": t.assigned_worker}
                    for t in self.tasks.values()
                    if t.recovery_started_at is not None and (job_id is None or t.job_id == job_id)]


class WorkerRegistry:
    def __init__(self, offline_after: float = 15):
        self.workers: dict[str, dict[str, Any]] = {}
        self.offline_after = offline_after
        self.lock = threading.RLock()

    def register(self, worker_id: str, ip: str, payload: dict[str, Any]) -> None:
        with self.lock:
            old = self.workers.get(worker_id, {})
            self.workers[worker_id] = {**old, **payload, "id": worker_id, "ip": ip,
                                       "last_seen": time.time(), "online": True}

    def heartbeat(self, worker_id: str, metrics: dict[str, Any]) -> bool:
        with self.lock:
            if worker_id not in self.workers:
                return False
            self.workers[worker_id].update(metrics)
            self.workers[worker_id].update(last_seen=time.time(), online=True)
            return True

    def refresh(self) -> list[str]:
        newly_offline, now = [], time.time()
        with self.lock:
            for worker_id, worker in self.workers.items():
                online = now-worker["last_seen"] <= self.offline_after
                if worker.get("online") and not online:
                    newly_offline.append(worker_id)
                worker["online"] = online
        return newly_offline

    def snapshot(self) -> list[dict[str, Any]]:
        self.refresh()
        with self.lock:
            return [dict(w) for w in self.workers.values()]


def aggregate_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    pixels = sum(int(r.get("valid_pixels") or 0) for r in rows)
    radiance = sum(float(r.get("sum_radiance") or 0) for r in rows)
    mins = [float(r["min_radiance"]) for r in rows if r.get("min_radiance") is not None]
    maxs = [float(r["max_radiance"]) for r in rows if r.get("max_radiance") is not None]
    return {"months": sum(int(r.get("months") or 0) for r in rows),
            "valid_pixels": pixels, "sum_radiance": radiance,
            "global_mean": radiance / pixels if pixels else None,
            "min_radiance": min(mins) if mins else None,
            "max_radiance": max(maxs) if maxs else None}


def result_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
