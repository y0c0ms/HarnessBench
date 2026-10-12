"""Runs (harness, task, rep) jobs through one shared pool. Every job is isolated:

  workspace   a fresh copy of the task's starter files plus its tests; tests are restored before grading
  home        a fresh private HOME holding only this harness's config (dummy key, proxy URL)
  proxy       its own logging proxy on its own unix socket and capture directory; holds the real key
  sandbox     bubblewrap: no network except a relay to that proxy; no view of the real home or other runs
  grading     the task's test command, run after the tests are restored; tampering is recorded, not hidden
"""
from __future__ import annotations

import concurrent.futures as cf
import dataclasses
import difflib
import fcntl
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from . import sandbox
from .config import Config
from .adapter import Harness
from .judge import judge_run
from .measure import ResourceSampler
from .tasks import Task

PROXY_START_S = 10


@dataclasses.dataclass
class Job:
    id: int
    harness: str
    task: str
    rep: int


def plan(cfg: Config, tasks: list[Task], harnesses: list[Harness],
         cells: set[tuple[str, str]] | None = None) -> list[Job]:
    """One job per (rep, task, harness). `cells` optionally restricts to explicit (harness, task) pairs."""
    jobs, jid = [], 0
    for rep in range(cfg.reps):
        for t in tasks:
            for h in harnesses:
                if cells is not None and (h.name, t.name) not in cells:
                    continue
                jobs.append(Job(jid, h.name, t.name, rep)); jid += 1
    return jobs


class State:
    """Thread-safe progress, shared by the pool and the display."""

    def __init__(self, jobs: list[Job], meta: dict | None = None):
        self.lock = threading.Lock()
        self.meta = meta or {}   # name -> harness object (label, icons) for display; optional
        self.total = len(jobs)
        self.done = 0
        self.passed = 0
        self.running: dict[int, dict] = {}
        self.recent: list[dict] = []
        self.per: dict[str, dict] = {}
        for j in jobs:
            s = self.per.setdefault(j.harness, {"total": 0, "done": 0, "passed": 0, "failed": 0, "killed": 0, "errors": 0})
            s["total"] += 1
        self.started = time.time()

    def begin(self, job: Job):
        with self.lock:
            self.running[job.id] = {"harness": job.harness, "task": job.task, "rep": job.rep, "t": time.time()}

    def end(self, job: Job, rec: dict):
        with self.lock:
            self.running.pop(job.id, None)
            self.done += 1
            s = self.per[job.harness]
            s["done"] += 1
            if rec.get("error"):
                s["errors"] += 1
            if rec.get("killed"):
                s["killed"] += 1
            elif rec["pass"]:
                self.passed += 1
                s["passed"] += 1
            else:
                s["failed"] += 1
            self.recent = ([{"harness": job.harness, "task": job.task, "rep": job.rep,
                             "pass": rec["pass"], "wall_s": rec["wall_s"]}] + self.recent)[:8]

    def snapshot(self):
        with self.lock:
            return {"total": self.total, "done": self.done, "passed": self.passed,
                    "running": dict(self.running), "recent": list(self.recent),
                    "per": {k: dict(v) for k, v in self.per.items()}, "started": self.started}


def _tests_tampered(ws: pathlib.Path, tests: pathlib.Path) -> bool:
    """Tests are copied to the workspace root; any edit, deletion, or addition to them is tampering."""
    for f in tests.rglob("*"):
        if f.is_file():
            copy = ws / f.relative_to(tests)
            if not copy.exists() or copy.read_bytes() != f.read_bytes():
                return True
    return False


def _workspace_diff(starter: pathlib.Path, ws: pathlib.Path, skip: set[str]) -> str:
    def read(p):
        return p.read_text(errors="replace").splitlines(keepends=True) if p.exists() else []
    rels = {p.relative_to(ws) for p in ws.rglob("*") if p.is_file()} | \
           {p.relative_to(starter) for p in starter.rglob("*") if p.is_file()}
    out = []
    for rel in sorted(rels, key=str):
        if rel.as_posix() in skip or "__pycache__" in rel.parts:
            continue
        a, b = read(starter / rel), read(ws / rel)
        if a != b:
            out += difflib.unified_diff(a, b, fromfile=f"starter/{rel}", tofile=f"workspace/{rel}")
    return "".join(out)


def _usage(capture: pathlib.Path) -> dict:
    n = p = c = cr = errors = rate_limited = 0
    served: set[str] = set()
    for f in capture.glob("*.json"):
        d = json.loads(f.read_text())
        if not any(p in d["path"] for p in ("/chat/completions", "/messages", "/responses")):   # the model requests
            continue
        n += 1
        p += d["usage"]["prompt"]
        c += d["usage"]["completion"]
        cr += d["usage"].get("cache_read", 0)
        if d.get("served_model"):
            served.add(d["served_model"])
        if d["status"] != 200:
            errors += 1
        if d["status"] == 429 or "rate limit" in (d.get("response_error") or "").lower():   # responses only: request bodies quote the phrase
            rate_limited += 1
    # What the provider said it served. More than one entry means the gateway moved the run to another model.
    return {"chat_requests": n, "prompt_tokens": p, "completion_tokens": c, "cache_read_tokens": cr,
            "http_errors": errors, "rate_limited": rate_limited,
            "served_models": ",".join(sorted(served)) or None}


def _start_proxy(cfg: Config, sock: pathlib.Path, capture: pathlib.Path) -> subprocess.Popen:
    p = cfg.provider
    cmd = [sys.executable, "-m", "agent_bench.proxy", "--sock", str(sock), "--out", str(capture),
           "--openai-base", p.openai_base_url, "--key-env", p.api_key_env]
    if p.anthropic_base_url:
        cmd += ["--anthropic-base", p.anthropic_base_url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    for _ in range(int(PROXY_START_S / 0.05)):
        if sock.exists() or proc.poll() is not None:
            break
        time.sleep(0.05)
    if proc.poll() is not None or not sock.exists():
        err = proc.stderr.read().decode(errors="replace")[:300] if proc.poll() is not None else "socket not created"
        raise RuntimeError(f"logging proxy failed to start: {err}")
    return proc


def _grade(ws: pathlib.Path, cmd: list[str]):
    try:
        p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "grader timed out"
    lines = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode == 0, (lines[-1] if lines else f"exit {p.returncode}")


class _KillWatch:
    """Stops the harness process tree when the operator's kill file appears. The viewer writes that file."""

    def __init__(self, proc, kill_file):
        self.proc, self.kill_file, self.fired = proc, kill_file, False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(0.3):
            if self.kill_file is not None and self.kill_file.exists() and self.proc.poll() is None:
                self.fired = True
                self.proc.kill()
                return

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=2)


def _write_live(path: pathlib.Path | None, **fields) -> None:
    """Live job state for the viewer. Written atomically; a missing path means no viewer is attached."""
    if path is None:
        return
    data = json.loads(path.read_text()) if path.exists() else {}
    data.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def run_one(cfg: Config, task: Task, harness: Harness, rep: int, attempt: int,
            run_root: pathlib.Path, judge_cfg, ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    kill_file, live = ctx.get("kill_file"), ctx.get("live_file")
    run_dir = run_root / "runs" / f"{harness.name}-{task.name}-r{rep}-a{attempt}"
    ws, home, capture = run_dir / "ws", run_dir / "home", run_dir / "capture"
    for d in (ws, home, capture):
        d.mkdir(parents=True)
    shutil.copytree(task.starter, ws, dirs_exist_ok=True)
    shutil.copytree(task.tests, ws, dirs_exist_ok=True)
    timeout = task.timeout_s or cfg.timeout_s
    rec = {"harness": harness.name, "task": task.name, "rep": rep, "attempt": attempt,
           "provider": cfg.provider.name, "model": cfg.provider.model,
           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": None, "timed_out": False, "exit": None,
           "killed": False, "settings": dict(cfg.settings)}
    _write_live(live, job=ctx.get("job"), harness=harness.name, task=task.name, rep=rep, attempt=attempt,
                phase="starting", started=time.time(), run_dir=str(run_dir))
    t0 = time.time()
    io_dir = pathlib.Path(tempfile.mkdtemp(prefix="agb-io-", dir="/tmp"))  # short path: unix sockets are length-limited
    proxy = None
    sampler = watch = None
    out_f = err_f = None
    try:
        if harness.needs_model:
            binary = harness.find(cfg.binaries.get(harness.name))
            proxy = _start_proxy(cfg, io_dir / "proxy.sock", capture)
            proxy_url = f"http://127.0.0.1:{sandbox.RELAY_PORT}"
            harness.write_config(home, cfg.provider, proxy_url, cfg.settings)
            env = {"PATH": f"{os.path.dirname(binary)}:/usr/local/bin:/usr/bin:/bin",
                   **harness.env(home, proxy_url, cfg.settings)}
            inner_cmd = harness.command(binary, cfg.provider, cfg.prompt)
            inner = (f"{sys.executable} {sandbox.RELAY_PATH} {sandbox.RELAY_PORT} {sandbox.IO_DIR}/proxy.sock "
                     f"& sleep 0.5; exec " + " ".join(shlex.quote(a) for a in inner_cmd))
            argv = sandbox.bwrap_argv(run_dir, io_dir, harness.install_roots(binary),
                                      os.path.expanduser("~"), ["sh", "-c", inner])
            # output goes straight to files, so the viewer can follow it live; the harness sees the same non-tty stdio
            out_f = open(run_dir / "harness.out", "w")
            err_f = open(run_dir / "harness.err", "w")
            try:
                p = subprocess.Popen(argv, cwd=ws, env=env, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f)
                roots = [p.pid] + ([proxy.pid] if proxy is not None else [])
                sampler = ResourceSampler(roots).start()
                watch = _KillWatch(p, kill_file).start()
                _write_live(live, phase="harness")
                try:
                    p.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    rec["timed_out"] = True
                    p.kill()
                    p.wait()
                rec["exit"] = None if rec["timed_out"] else p.returncode
            finally:
                if watch is not None:
                    watch.stop()
                    rec["killed"] = watch.fired
                if sampler is not None:
                    rec["resources"] = sampler.stop()
                out_f.close()
                err_f.close()
        else:
            # built-in oracle: apply the reference solution; no model, no proxy, no sandbox
            shutil.copytree(task.reference, ws, dirs_exist_ok=True)
            rec["exit"] = 0
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    finally:
        rec["wall_s"] = round(time.time() - t0, 1)
        if proxy is not None:
            proxy.terminate()
            try:
                proxy.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proxy.kill()
        shutil.rmtree(io_dir, ignore_errors=True)

    skip = {f.relative_to(task.tests).as_posix() for f in task.tests.rglob("*") if f.is_file()}
    if rec["killed"]:
        # an operator kill is neither a pass nor a fail: no grading, no judge, partial usage kept
        rec.update({"pass": False, "pytest": "killed by operator", "tests_tampered": False})
    else:
        _write_live(live, phase="grading")
        tampered = _tests_tampered(ws, task.tests)
        shutil.copytree(task.tests, ws, dirs_exist_ok=True)          # restore pristine tests before grading
        passed, summary = _grade(ws, cfg.grade_cmd)
        rec.update({"pass": passed, "pytest": summary, "tests_tampered": tampered})
    diff = _workspace_diff(task.starter, ws, skip)
    (run_dir / "change.diff").write_text(diff)
    rec.update(_usage(capture))
    if judge_cfg is not None and not rec["error"] and not rec["killed"]:
        _write_live(live, phase="judging")
        rec["judge"] = judge_run(judge_cfg, task, diff, rec["pass"], rec["pytest"])
    rec["run_dir"] = str(run_dir)
    if not cfg.keep_workspaces:
        shutil.rmtree(ws, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
    _write_live(live, phase="killed" if rec["killed"] else "done")
    return rec


def _queued_kill_record(cfg: Config, task: Task, harness: Harness, rep: int) -> dict:
    """A job killed before it started: recorded as killed, with zero usage, so it is never silently dropped."""
    return {"harness": harness.name, "task": task.name, "rep": rep, "attempt": 0,
            "provider": cfg.provider.name, "model": cfg.provider.model, "started": None,
            "error": None, "timed_out": False, "exit": None, "killed": True, "pass": False,
            "pytest": "killed by operator before start", "tests_tampered": False, "wall_s": 0.0,
            "chat_requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cache_read_tokens": 0,
            "http_errors": 0, "rate_limited": 0, "run_dir": None}


def acquire_slot(slot_dir: pathlib.Path, n: int, poll_s: float = 0.5):
    """Blocks until one of n global session slots is free, then returns its open file (the slot is held while open).
    Slots are flock()s on files in slot_dir, so every agent-bench process using the same work dir shares the cap:
    a later run queues behind the runs already in flight and takes each slot as it frees. A dead process releases
    its slots automatically."""
    slot_dir.mkdir(parents=True, exist_ok=True)
    while True:
        for i in range(n):
            fh = open(slot_dir / f"slot-{i}.lock", "a")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fh
            except BlockingIOError:
                fh.close()
        time.sleep(poll_s)


def run_all(cfg: Config, tasks: list[Task], harnesses: list[Harness], run_root: pathlib.Path,
            state: State, log, judge_cfg=None, jobs: list[Job] | None = None) -> list[dict]:
    """Runs the planned jobs through a pool of cfg.max_sessions workers. Records are appended to
    run_root/results.jsonl as each job finishes, so a partial run is still a valid partial result.
    plan.json, live/ and control/ are what the viewer reads and writes; they never change a result."""
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "live").mkdir(exist_ok=True)
    (run_root / "control").mkdir(exist_ok=True)
    out_file = run_root / "results.jsonl"
    jobs = jobs if jobs is not None else plan(cfg, tasks, harnesses)
    (run_root / "plan.json").write_text(json.dumps(
        [{"id": j.id, "harness": j.harness, "task": j.task, "rep": j.rep} for j in jobs]))
    (run_root / "settings.json").write_text(json.dumps(cfg.settings, indent=2))   # the values this run used
    by_h = {h.name: h for h in harnesses}
    by_t = {t.name: t for t in tasks}
    write_lock = threading.Lock()

    def _run_job(j: Job):
        state.begin(j)
        h, t = by_h[j.harness], by_t[j.task]
        kill_file = run_root / "control" / f"job-{j.id}.kill"
        ctx = {"job": j.id, "kill_file": kill_file, "live_file": run_root / "live" / f"job-{j.id}.json"}
        recs = []
        for attempt in range(max(cfg.attempts, 1)):
            if kill_file.exists():
                break
            recs.append(run_one(cfg, t, h, j.rep, attempt, run_root, judge_cfg, ctx))
            if recs[-1]["killed"]:
                break
        if not recs:
            recs.append(_queued_kill_record(cfg, t, h, j.rep))
            _write_live(ctx["live_file"], job=j.id, phase="killed")
        for attempt in range(len(recs), 1 + cfg.retry_failed):
            if kill_file.exists() or recs[-1]["pass"] or recs[-1]["error"] or recs[-1]["killed"]:
                break
            recs.append(run_one(cfg, t, h, j.rep, attempt, run_root, judge_cfg, ctx))
        with write_lock, open(out_file, "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        final = recs[-1]
        state.end(j, final)
        log(f"[{state.done}/{state.total}] {j.harness} {j.task} rep{j.rep}: "
            f"{'KILLED' if final['killed'] else ('PASS' if final['pass'] else 'FAIL')} {final['wall_s']}s"
            + (f" error={final['error']}" if final["error"] else ""))
        return final

    def job(j: Job):
        slot = acquire_slot(cfg.work_dir / "slots", cfg.max_sessions)
        try:
            return _run_job(j)
        finally:
            slot.close()

    with cf.ThreadPoolExecutor(max_workers=cfg.max_sessions) as ex:
        return list(ex.map(job, jobs))
