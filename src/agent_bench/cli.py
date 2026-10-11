"""agent-bench command line.

    agent-bench init                       write a starter bench.toml and an example task
    agent-bench harnesses -c bench.toml    list the harness plugins and whether each is runnable
    agent-bench validate  -c bench.toml    check every task: tests fail on the starter, pass on the reference
    agent-bench run       -c bench.toml    choose harnesses (tick list), then run the matrix
    agent-bench report    RUN_DIR          summarise a finished or partial run
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import shutil
import sys
import threading
import time

from . import __version__, config as cfgmod, results, runner, sandbox, settings as settingsmod, tasks as taskmod
from .adapter import Harness, load_registry
from .picker import tick_list

PKG = pathlib.Path(__file__).resolve().parent
EXAMPLES = PKG.parent.parent / "examples"


def cmd_init(args) -> int:
    target = pathlib.Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    cfg = target / "bench.toml"
    if cfg.exists() and not args.force:
        print(f"{cfg} exists (use --force)")
        return 1
    shutil.copy(EXAMPLES / "bench.example.toml", cfg)
    shutil.copytree(EXAMPLES / "tasks", target / "tasks", dirs_exist_ok=True)
    (target / "harnesses").mkdir(exist_ok=True)
    shutil.copy(PKG.parent.parent / "harnesses" / "_template.py", target / "harnesses" / "_template.py")
    print(f"wrote {cfg}, {target / 'tasks'}/ and {target / 'harnesses'}/ (add one .py per harness there)")
    return 0


def _load(args):
    cfg = cfgmod.load(args.config)
    if getattr(args, "harness", None):
        cfg.harnesses = args.harness.split(",")
    if getattr(args, "max_sessions", None):
        cfg.max_sessions = args.max_sessions
    if getattr(args, "reps", None):
        cfg.reps = args.reps
    if getattr(args, "retry_failed", None) is not None:
        cfg.retry_failed = args.retry_failed
    if getattr(args, "attempts", None):
        cfg.attempts = args.attempts
    if getattr(args, "task", None):
        cfg.task_filter = args.task.split(",")
    if getattr(args, "ascii", False):
        cfg.icons = "ascii"
    if getattr(args, "judge", None) is True and cfg.judge is None:
        raise cfgmod.ConfigError("--judge requires an enabled [judge] section in the config")
    if getattr(args, "judge", None) is False:
        cfg.judge = None
    return cfg


def _registry(cfg):
    try:
        return load_registry(cfg.harness_dir)
    except ValueError as e:
        raise cfgmod.ConfigError(str(e))


def _status(h: Harness, cfg) -> str | None:
    """None if runnable, else the reason it is not."""
    if not h.needs_model:
        return None
    reason = h.unavailable_reason(cfg.provider)
    if reason:
        return reason
    if not h.find(cfg.binaries.get(h.name)):
        return f"executable '{h.executable}' not found (set [binaries] {h.name} in the config)"
    return None


def cmd_harnesses(args) -> int:
    cfg = _load(args)
    reg = _registry(cfg)
    print(f"plugins in {cfg.harness_dir}: {len(reg) - 1} (plus built-in oracle)  provider: {cfg.provider.name}")
    for name, h in reg.items():
        if not h.needs_model:
            print(f"  {name:10} built-in self-test (no model)")
            continue
        st = _status(h, cfg)
        print(f"  {name:10} {'ok: ' + (h.find(cfg.binaries.get(name)) or '') if st is None else st}")
    print(f"sandbox (bubblewrap): {'available' if sandbox.available() else 'MISSING'}")
    return 0


def cmd_validate(args) -> int:
    cfg = _load(args)
    tasks = taskmod.discover(cfg.tasks_dir, cfg.task_filter)
    bad = 0
    for t in tasks:
        rep = taskmod.validate(t, cfg.grade_cmd)
        mark = "OK  " if rep["ok"] else "FAIL"
        bad += not rep["ok"]
        print(f"{mark} {t.name}: starter {'fails' if rep['starter_fails'] else 'PASSES (task is trivial)'}"
              f" [{rep['starter']}]; reference {rep['reference']}")
    print(f"{len(tasks) - bad}/{len(tasks)} tasks valid")
    return 0 if bad == 0 else 1


def _parse_cells(text: str) -> set[tuple[str, str]]:
    """'pi:T7,omp:T8' -> {('pi','T7'), ('omp','T8')}. Anything else is a configuration error."""
    cells = set()
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if item.count(":") != 1 or not all(item.split(":")):
            raise cfgmod.ConfigError(f"--cells entry '{item}' must look like harness:task")
        cells.add(tuple(item.split(":", 1)))
    return cells

def _choose_harnesses(args, cfg, reg) -> list[Harness] | None:
    """Named harnesses (flag, then config), or the tick list on a terminal. Returns None if nothing is chosen."""
    named = (args.harness.split(",") if getattr(args, "harness", None) else None) or cfg.harnesses or None
    if named:
        unknown = [n for n in named if n not in reg]
        if unknown:
            raise cfgmod.ConfigError(f"unknown harness(es) {unknown}; available: {sorted(reg)}")
        return [reg[n] for n in named]
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise cfgmod.ConfigError("no harnesses selected: set [run] harnesses, pass --harness, or run in a terminal")
    items = [{"name": n, "label": h.label, "status": (_status(h, cfg) if h.needs_model else "built-in self-test")}
             for n, h in reg.items() if n != "oracle"]
    preselected = {i["name"] for i in items if i["status"] is None}
    picked = tick_list(items, preselected)
    return [reg[n] for n in picked] if picked else None


def cmd_run(args) -> int:
    cfg = _load(args)
    if not sandbox.available():
        print("bubblewrap (bwrap) is required for harness runs; install it or use only the oracle harness")
        return 2
    reg = _registry(cfg)
    tasks = taskmod.discover(cfg.tasks_dir, cfg.task_filter)
    if not tasks:
        print("no tasks selected")
        return 2
    chosen_all = _choose_harnesses(args, cfg, reg)
    if not chosen_all:
        print("no harnesses selected")
        return 2
    chosen = []
    for h in chosen_all:
        st = _status(h, cfg)
        if st is not None:
            print(f"skip {h.name}: {st}")
            continue
        chosen.append(h)
    if not chosen:
        print("no runnable harnesses")
        return 2
    if any(h.needs_model for h in chosen) and not os.environ.get(cfg.provider.api_key_env):
        print(f"set {cfg.provider.api_key_env} (the provider key) in the environment")
        return 2
    if cfg.judge is not None and not os.environ.get(cfg.judge.api_key_env):
        print(f"set {cfg.judge.api_key_env} (the judge key) or run with --no-judge")
        return 2

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = cfg.work_dir / stamp
    run_root.mkdir(parents=True, exist_ok=True)
    cells = _parse_cells(args.cells) if getattr(args, "cells", None) else None
    jobs = runner.plan(cfg, tasks, chosen, cells)
    if not jobs:
        print("no jobs: check --cells against the selected harnesses and tasks")
        return 2
    state = runner.State(jobs, meta={h.name: h for h in chosen})
    log_path = run_root / "log.txt"
    lock = threading.Lock()
    use_tui = sys.stdout.isatty() and not args.no_tui

    def log(msg):
        with lock:
            with open(log_path, "a") as fh:
                fh.write(time.strftime("%H:%M:%S ") + msg + "\n")
            if not use_tui:
                print(msg, flush=True)

    print(f"run {run_root}: {len(jobs)} jobs, harnesses {[h.name for h in chosen]}, {len(tasks)} tasks, "
          f"max {cfg.max_sessions} sessions in flight")
    worker_err = []

    def work():
        try:
            runner.run_all(cfg, tasks, chosen, run_root, state, log, judge_cfg=cfg.judge, jobs=jobs)
        except Exception as e:  # surfaced after the display closes
            worker_err.append(e)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    if use_tui:
        from .tui import Display
        with Display(state, cfg.max_sessions, cfg.icons) as disp:
            while th.is_alive():
                disp.tick()
                time.sleep(0.25)
            disp.tick()
    else:
        while th.is_alive():
            time.sleep(0.5)
    th.join()
    if worker_err:
        print(f"run aborted: {worker_err[0]}")
        return 1
    summary = results.write_summary(run_root)
    print(f"\nsummary: {summary}\n")
    print(summary.read_text())
    return 0


def _cfg_or_none(args):
    return _load(args) if getattr(args, "config", None) else None


def cmd_watch(args) -> int:
    from . import watch as watchmod
    run_root = pathlib.Path(args.run_dir)
    if not (run_root / "plan.json").exists():
        print(f"no plan.json in {run_root} (not a run directory)")
        return 1
    if args.once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        watchmod.print_once(run_root)
        return 0
    watchmod.run_tui(run_root, _cfg_or_none(args))
    return 0


def cmd_settings(args) -> int:
    from . import watch as watchmod
    cfg = _load(args)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        for s in settingsmod.CATALOG:
            v = cfg.settings.get(s.key)
            print(f"{s.key} = {'unset' if v is None else v}")
        return 0
    watchmod.run_tui(None, cfg)
    return 0


def cmd_check_settings(args) -> int:
    from . import settings_check
    cfg = _load(args)
    reg = _registry(cfg)
    chosen = [h for h in reg.values() if h.needs_model and not _status(h, cfg)]
    if not chosen:
        print("no runnable harnesses to check")
        return 2
    if not os.environ.get(cfg.provider.api_key_env):
        print(f"set {cfg.provider.api_key_env} (the provider key) in the environment")
        return 2
    report = settings_check.check(cfg, chosen)
    settings_check.save_report(cfg, report)
    for name, r in report.items():
        err = f"  error: {r['error']}" if r["error"] else ""
        print(f"{name:10} applied {r['applied'] or '-'}   not applied {r['not_applied'] or '-'}   "
              f"requests {r['requests']}{err}")
    print(f"saved to {settingsmod.support_path(cfg.settings_file)}")
    return 0





def cmd_report(args) -> int:
    run_root = pathlib.Path(args.run_dir)
    if not (run_root / "results.jsonl").exists():
        print(f"no results.jsonl in {run_root}")
        return 1
    path = results.write_summary(run_root)
    print(path.read_text())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="agent-bench", description="Compare coding-agent harnesses on the same tasks.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="write a starter config, example task, and harness folder")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("harnesses", help="list harness plugins and their status")
    p.add_argument("-c", "--config", default="bench.toml")
    p.set_defaults(fn=cmd_harnesses)

    p = sub.add_parser("validate", help="check task tests against starter and reference")
    p.add_argument("-c", "--config", default="bench.toml")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("run", help="choose harnesses and run the benchmark matrix")
    p.add_argument("-c", "--config", default="bench.toml")
    p.add_argument("--harness", help="comma list; skips the tick list")
    p.add_argument("--task", help="comma list of task names, overrides config")
    p.add_argument("--reps", type=int)
    p.add_argument("--max-sessions", type=int, help="cap on sessions in flight across all harnesses")
    p.add_argument("--retry-failed", type=int)
    p.add_argument("--attempts", type=int, help="attempts per job, all run (for averages); overrides config")
    p.add_argument("--cells", help="only these harness:task pairs, e.g. pi:T7,omp:T8")
    judge = p.add_mutually_exclusive_group()
    judge.add_argument("--judge", dest="judge", action="store_true", default=None)
    judge.add_argument("--no-judge", dest="judge", action="store_false")
    p.add_argument("--ascii", action="store_true", help="ASCII icons instead of emoji")
    p.add_argument("--no-tui", action="store_true", help="plain line output even on a terminal")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("report", help="summarise a run directory")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("watch", help="view a run live: table, per-session output, kill requests, settings")
    p.add_argument("run_dir")
    p.add_argument("-c", "--config", help="config file; enables the settings screen (press s)")
    p.add_argument("--once", action="store_true", help="print the table once and exit")
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("settings", help="open the general settings screen")
    p.add_argument("-c", "--config", default="bench.toml")
    p.set_defaults(fn=cmd_settings)

    p = sub.add_parser("check-settings", help="confirm on the wire which settings each harness applies")
    p.add_argument("-c", "--config", default="bench.toml")
    p.set_defaults(fn=cmd_check_settings)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except (cfgmod.ConfigError, taskmod.TaskError) as e:
        print(f"config error: {e}")
        return 2
