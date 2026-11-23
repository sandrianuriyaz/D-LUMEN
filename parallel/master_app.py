from __future__ import annotations

import os
import socket
import threading
import time
import uuid
import fnmatch
from functools import wraps

from flask import Flask, jsonify, render_template_string, request

from parallel.core import TaskStore, WorkerRegistry, aggregate_results, make_tasks
from parallel.eventlog import EventLog

TOKEN = os.getenv("DLUMEN_TOKEN", "")
MASTER_PORT = int(os.getenv("DLUMEN_MASTER_PORT", "5050"))
DISCOVERY_PORT = int(os.getenv("DLUMEN_DISCOVERY_PORT", "5005"))
HEARTBEAT_TIMEOUT = float(os.getenv("DLUMEN_HEARTBEAT_TIMEOUT", "15"))
TASK_TIMEOUT = float(os.getenv("DLUMEN_TASK_TIMEOUT", "120"))

app = Flask(__name__)
registry = WorkerRegistry(HEARTBEAT_TIMEOUT)
store = TaskStore(int(os.getenv("DLUMEN_MAX_RETRIES", "2")))
started_at = time.time()
jobs: dict[str, dict] = {}
events = EventLog(os.getenv("DLUMEN_EVENT_LOG", "results/runtime/events.jsonl"))


def protected(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not TOKEN or request.headers.get("X-DLUMEN-Token") != TOKEN:
            return jsonify(error="unauthorized"), 401
        return fn(*args, **kwargs)
    return wrapper


@app.get("/health")
def health():
    return jsonify(status="online", role="master", uptime=time.time()-started_at)


@app.post("/api/register")
@protected
def register():
    data = request.get_json(silent=True) or {}
    worker_id = data.get("worker_id")
    if not worker_id or not isinstance(data.get("port"), int):
        return jsonify(error="worker_id dan port valid wajib diisi"), 400
    registry.register(worker_id, request.remote_addr, data)
    events.emit("worker_registered", worker_id=worker_id, ip=request.remote_addr,
                port=data["port"], processes=data.get("processes"))
    return jsonify(status="registered", heartbeat_interval=5)


@app.post("/api/heartbeat")
@protected
def heartbeat():
    data = request.get_json(silent=True) or {}
    if not registry.heartbeat(data.get("worker_id", ""), data.get("metrics", {})):
        return jsonify(status="register_required"), 404
    return jsonify(status="ok")


@app.get("/api/workers")
def workers():
    return jsonify(registry.snapshot())


@app.post("/api/jobs")
@protected
def create_job():
    data = request.get_json(silent=True) or {}
    job_id = str(uuid.uuid4())
    active_workers = [w for w in registry.snapshot() if w["online"]]
    worker_limit = int(data.get("worker_count", len(active_workers) or 0))
    selected_workers = [w["id"] for w in sorted(active_workers, key=lambda w: w["id"])[:worker_limit]]
    if not selected_workers:
        return jsonify(error="job membutuhkan minimal satu worker aktif"), 409
    try:
        tasks = make_tasks(data.get("operation", "aggregate"), int(data.get("start_year", 2020)),
                           int(data.get("end_year", 2025)), int(data.get("months_per_task", 1)),
                           data.get("replicas"), data.get("params"), job_id)
    except (TypeError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    # Jika Worker mengiklankan partisi, jadikan metadata itu sumber kebenaran.
    advertised = {w["id"]: w.get("partitions", []) for w in active_workers if w.get("partitions")}
    if advertised and not data.get("replicas"):
        for task in tasks:
            task.eligible_workers = [wid for wid, patterns in advertised.items()
                if any(fnmatch.fnmatch(task.partition_id, p) or task.partition_id.startswith(p) for p in patterns)]
    scheduling = data.get("scheduling", "dynamic")
    if scheduling not in ("dynamic", "static"):
        return jsonify(error="scheduling harus static atau dynamic"), 400
    if scheduling == "static":
        active = selected_workers
        if not active:
            return jsonify(error="static scheduling membutuhkan worker aktif"), 409
        for index, task in enumerate(tasks):
            compatible = task.eligible_workers or active
            choices = [w for w in active if w in compatible]
            if choices:
                task.params["_static_worker"] = choices[index % len(choices)]
    for task in tasks:
        allowed = set(task.eligible_workers or selected_workers) & set(selected_workers)
        task.eligible_workers = sorted(allowed)
    if any(not task.eligible_workers for task in tasks):
        return jsonify(error="ada partisi tanpa worker/replika dalam worker yang dipilih"), 409
    store.add(tasks)
    jobs[job_id] = {"job_id": job_id, "created_at": time.time(), "scheduling": scheduling,
                    "worker_ids": selected_workers, "operation": data.get("operation", "aggregate")}
    events.emit("job_created", job_id=job_id, operation=data.get("operation", "aggregate"),
                scheduling=scheduling, task_count=len(tasks), worker_ids=selected_workers)
    return jsonify(job_id=job_id, task_ids=[t.task_id for t in tasks], count=len(tasks),
                   worker_ids=selected_workers), 201


@app.post("/api/tasks/claim")
@protected
def claim():
    data = request.get_json(silent=True) or {}
    worker_id = data.get("worker_id", "")
    task = store.claim(worker_id, set(data["partitions"]) if data.get("partitions") else None)
    if task:
        events.emit("task_assigned", job_id=task.job_id, task_id=task.task_id,
                    partition_id=task.partition_id, worker_id=worker_id, attempt=task.attempts)
    return (jsonify(task=task.public()) if task else (jsonify(task=None), 204))


@app.post("/api/tasks/<task_id>/result")
@protected
def result(task_id):
    data = request.get_json(silent=True) or {}
    accepted = store.complete(task_id, data.get("worker_id", ""), data.get("result", {}))
    task = store.tasks.get(task_id)
    events.emit("task_completed" if accepted else "duplicate_or_late_result",
                task_id=task_id, job_id=task.job_id if task else None,
                worker_id=data.get("worker_id"))
    return jsonify(accepted=accepted), 200 if accepted else 409


@app.post("/api/tasks/<task_id>/fail")
@protected
def failed(task_id):
    if task_id not in store.tasks:
        return jsonify(error="task tidak ditemukan"), 404
    store.fail(task_id, (request.get_json(silent=True) or {}).get("error", "worker error"))
    task = store.tasks[task_id]
    events.emit("task_failed", task_id=task_id, job_id=task.job_id, status=task.status.value,
                error=task.error)
    return jsonify(status=store.tasks[task_id].status.value)


@app.get("/api/status")
def status():
    job_id = request.args.get("job_id")
    if job_id and job_id not in jobs:
        return jsonify(error="job tidak ditemukan"), 404
    counts = store.counts(job_id)
    result_values = store.job_results(job_id) if job_id else list(store.results.values())
    total = sum(counts.values())
    worker_rows = registry.snapshot()
    cpu = [w["cpu_percent"] for w in worker_rows if isinstance(w.get("cpu_percent"), (int, float))]
    memory = [w["memory_percent"] for w in worker_rows if isinstance(w.get("memory_percent"), (int, float))]
    return jsonify(job=jobs.get(job_id), workers=worker_rows, tasks=counts,
                   progress=(counts["completed"]/total*100 if total else 0),
                   aggregate=aggregate_results(result_values), recovery=store.recovery_events(job_id),
                   metrics={"mean_cpu_percent": sum(cpu)/len(cpu) if cpu else None,
                            "mean_memory_percent": sum(memory)/len(memory) if memory else None})


@app.get("/api/results")
def results():
    job_id = request.args.get("job_id")
    values = store.job_results(job_id) if job_id else list(store.results.values())
    return jsonify(results=values, aggregate=aggregate_results(values), recovery=store.recovery_events(job_id))


@app.get("/api/events")
def event_history():
    return jsonify(events.read(min(1000, int(request.args.get("limit", 200)))))


@app.get("/")
def dashboard():
    return render_template_string(DASHBOARD)


def discovery_broadcast(stop: threading.Event | None = None):
    stop = stop or threading.Event()
    payload = f"DLUMEN_MASTER_V2|{MASTER_PORT}".encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not stop.wait(3):
            try: sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
            except OSError: app.logger.warning("UDP broadcast gagal", exc_info=True)


def monitor(stop: threading.Event | None = None):
    stop = stop or threading.Event()
    while not stop.wait(2):
        for worker_id in registry.refresh():
            recovered = store.recover_worker(worker_id)
            events.emit("worker_offline", worker_id=worker_id, requeued_tasks=recovered)
        for task_id in store.expire(TASK_TIMEOUT):
            events.emit("task_timeout", task_id=task_id)


DASHBOARD = r"""<!doctype html><html lang=id><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>D-LUMEN Dashboard</title>
<style>
:root{color-scheme:dark;--bg:#07121d;--panel:#10283d;--line:#284962;--blue:#57b7ff;--green:#62d79b;--red:#ff7587;--muted:#9cb2c5}
*{box-sizing:border-box}body{margin:0;font:14px system-ui;background:var(--bg);color:#edf7ff}header{padding:22px 4%;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}h1,h2{margin:.2em 0}main{padding:22px 4%;max-width:1500px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}.value{font-size:27px;font-weight:750;color:var(--blue)}.muted{color:var(--muted)}.online{color:var(--green)}.offline{color:var(--red)}
.panel{margin-top:16px}form{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;align-items:end}label{display:grid;gap:5px;color:var(--muted)}input,select,button{font:inherit;border-radius:7px;border:1px solid var(--line);padding:9px;background:#091c2b;color:white}button{background:#147ec1;border:0;font-weight:700;cursor:pointer}button:disabled{opacity:.5}table{width:100%;border-collapse:collapse;margin-top:10px}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line)}progress{width:100%;height:18px}#message{min-height:22px;margin-top:9px}.error{color:var(--red)}.success{color:var(--green)}code{word-break:break-all}@media(max-width:650px){.optional{display:none}}
</style>
<header><div><h1>D-LUMEN</h1><span class=muted>Distributed Light Pollution Monitoring</span></div><b class=online>● MASTER ONLINE</b></header>
<main>
<section class=grid><div class=card><div class=muted>Worker online</div><div class=value id=online>0</div></div><div class=card><div class=muted>Progress</div><div class=value id=progressText>0%</div></div><div class=card><div class=muted>CPU rata-rata</div><div class=value id=cpu>–</div></div><div class=card><div class=muted>RAM rata-rata</div><div class=value id=ram>–</div></div><div class=card><div class=muted>Task selesai</div><div class=value id=completed>0</div></div><div class=card><div class=muted>Task gagal</div><div class=value id=failed>0</div></div></section>
<section class=panel><h2>Jalankan Query</h2><form id=jobForm>
<label>Token<input id=token type=password required placeholder="DLUMEN_TOKEN"></label>
<label>Operation<select id=operation><option value=raster_aggregate>Raster aggregate</option><option value=aggregate>Database aggregate</option><option value=annual>Annual analysis</option><option value=trend>Trend analysis</option><option value=highest>Highest radiance</option><option value=lowest>Lowest radiance</option></select></label>
<label>Scheduling<select id=scheduling><option value=dynamic>Dynamic</option><option value=static>Static</option></select></label>
<label>Tahun awal<input id=startYear type=number value=2020 min=2000 max=2100></label><label>Tahun akhir<input id=endYear type=number value=2025 min=2000 max=2100></label>
<label>Bulan/task<input id=months type=number value=1 min=1 max=72></label><label>Jumlah worker<input id=workerCount type=number value=2 min=1 max=9></label>
<button id=run type=submit>Jalankan Job</button></form><div id=message></div><div id=jobInfo class=muted></div><progress id=bar max=100 value=0></progress></section>
<section class=panel><h2>Worker</h2><table><thead><tr><th>ID</th><th>Status</th><th>IP:Port</th><th>Proses</th><th>CPU</th><th>RAM</th><th class=optional>Partisi</th></tr></thead><tbody id=workerRows></tbody></table></section>
<section class=grid style="margin-top:16px"><div class=panel style=margin-top:0><h2>Status Task</h2><table><tbody id=taskRows></tbody></table></div><div class=panel style=margin-top:0><h2>Hasil Agregasi</h2><table><tbody id=aggregateRows></tbody></table></div></section>
<section class=panel><h2>Fault Recovery</h2><table><thead><tr><th>Task</th><th>Partisi</th><th>Attempts</th><th>Status</th><th>Recovery</th></tr></thead><tbody id=recoveryRows></tbody></table></section>
</main><script>
let jobId=null; const $=id=>document.getElementById(id); const fmt=v=>v==null?'–':(typeof v==='number'?v.toLocaleString('id-ID',{maximumFractionDigits:3}):v);
$('token').value=sessionStorage.getItem('dlumenToken')||'';
$('jobForm').addEventListener('submit',async e=>{e.preventDefault();$('run').disabled=true;$('message').textContent='Membuat job…';$('message').className='';let token=$('token').value;sessionStorage.setItem('dlumenToken',token);
 let body={operation:$('operation').value,scheduling:$('scheduling').value,start_year:+$('startYear').value,end_year:+$('endYear').value,months_per_task:+$('months').value,worker_count:+$('workerCount').value};
 try{let r=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json','X-DLUMEN-Token':token},body:JSON.stringify(body)}),j=await r.json();if(!r.ok)throw Error(j.error||r.statusText);jobId=j.job_id;$('message').textContent=`Job dibuat: ${j.count} task pada ${j.worker_ids.length} worker`;$('message').className='success';$('jobInfo').textContent=`Job ID: ${jobId}`}
 catch(err){$('message').textContent=err.message;$('message').className='error'}finally{$('run').disabled=false;refresh()}});
function rows(target,obj){$(target).innerHTML=Object.entries(obj).map(([k,v])=>`<tr><th>${k.replaceAll('_',' ')}</th><td>${fmt(v)}</td></tr>`).join('')}
async function refresh(){try{let url='/api/status'+(jobId?'?job_id='+encodeURIComponent(jobId):''),r=await fetch(url),j=await r.json();if(!r.ok)throw Error(j.error);let online=j.workers.filter(w=>w.online).length;$('online').textContent=online;$('progressText').textContent=j.progress.toFixed(1)+'%';$('bar').value=j.progress;$('cpu').textContent=fmt(j.metrics.mean_cpu_percent)+(j.metrics.mean_cpu_percent==null?'':'%');$('ram').textContent=fmt(j.metrics.mean_memory_percent)+(j.metrics.mean_memory_percent==null?'':'%');$('completed').textContent=j.tasks.completed;$('failed').textContent=j.tasks.failed;
 $('workerRows').innerHTML=j.workers.map(w=>`<tr><td>${w.id}</td><td class=${w.online?'online':'offline'}>${w.online?'ONLINE':'OFFLINE'}</td><td>${w.ip}:${w.port}</td><td>${fmt(w.processes)}</td><td>${fmt(w.cpu_percent)}%</td><td>${fmt(w.memory_percent)}%</td><td class=optional>${(w.partitions||[]).join(', ')||'semua'}</td></tr>`).join('')||'<tr><td colspan=7>Belum ada Worker terdaftar</td></tr>';rows('taskRows',j.tasks);rows('aggregateRows',j.aggregate);
 $('recoveryRows').innerHTML=j.recovery.map(x=>`<tr><td><code>${x.task_id.slice(0,8)}…</code></td><td>${x.partition_id}</td><td>${x.attempts}</td><td>${x.status}</td><td>${x.recovery_seconds==null?'berlangsung':fmt(x.recovery_seconds)+' s'}</td></tr>`).join('')||'<tr><td colspan=5>Belum ada recovery event</td></tr>'}catch(err){console.error(err)}}refresh();setInterval(refresh,2000);
</script></html>"""


def main():
    if not TOKEN:
        raise SystemExit("DLUMEN_TOKEN wajib diatur")
    threading.Thread(target=discovery_broadcast, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=MASTER_PORT, threaded=True)


if __name__ == "__main__":
    main()
