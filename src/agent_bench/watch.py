"""Operator viewer. A separate process: it reads run directories, writes kill requests, and edits the general
settings file. The runner does no drawing, so the viewer cannot affect a run's timings.

Keys
  table:     v view the highlighted running job   d / a move the highlight   k kill it
             s settings (needs -c config)         q quit viewer
  view:      d next running job   a previous   k kill   b / Esc back to table   q quit viewer
  settings:  up / down select   Enter edit   x unset   b / Esc back (or quit when opened standalone)
  kill:      k asks for confirmation; y confirms; any other key cancels.
Quitting the viewer never stops a run.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time

from . import results as resultsmod
from . import settings as settingsmod

TEST_ID = re.compile(r"(test_\w+\.py::\w+)")


def _tokens(run_dir: pathlib.Path | None) -> dict:
    """Usage from the proxy's records for one attempt. Records are written when a request completes."""
    out = {"prompt": 0, "completion": 0, "requests": 0}
    if run_dir is None:
        return out
    for f in (run_dir / "capture").glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if any(p in d.get("path", "") for p in ("/chat/completions", "/messages", "/responses")):
            out["requests"] += 1
            out["prompt"] += d["usage"]["prompt"]
            out["completion"] += d["usage"]["completion"]
    return out


def _output_tail(run_dir: pathlib.Path | None, lines: int = 15) -> tuple[list[str], str | None]:
    if run_dir is None or not (run_dir / "harness.out").exists():
        return [], None
    text = (run_dir / "harness.out").read_text(errors="replace")[-200_000:]
    found = TEST_ID.findall(text)
    return text.splitlines()[-lines:], (found[-1] if found else None)


def load(run_root: pathlib.Path) -> dict:
    run_root = pathlib.Path(run_root)
    plan_f = run_root / "plan.json"
    plan = json.loads(plan_f.read_text()) if plan_f.exists() else []
    recs = resultsmod.load(run_root / "results.jsonl") if (run_root / "results.jsonl").exists() else []
    finished: dict[tuple, list[dict]] = {}
    for r in recs:
        finished.setdefault((r["harness"], r["task"], r["rep"]), []).append(r)
    live: dict[int, dict] = {}
    for f in (run_root / "live").glob("job-*.json") if (run_root / "live").exists() else []:
        try:
            d = json.loads(f.read_text())
            live[int(d["job"])] = d
        except (OSError, ValueError, KeyError):
            continue
    jobs = []
    now = time.time()
    for j in plan:
        key = (j["harness"], j["task"], j["rep"])
        entry = {"id": j["id"], "harness": j["harness"], "task": j["task"], "rep": j["rep"],
                 "status": "queued", "attempt": None, "phase": None, "elapsed": None, "tokens": None,
                 "kill_requested": (run_root / "control" / f"job-{j['id']}.kill").exists()}
        if key in finished:
            rs = finished[key]
            entry["status"] = "killed" if any(r.get("killed") for r in rs) else ("pass" if rs[-1]["pass"] else "fail")
            entry["wall_s"] = sum(r["wall_s"] for r in rs)
            entry["tokens"] = {"prompt": sum(r["prompt_tokens"] for r in rs),
                               "completion": sum(r["completion_tokens"] for r in rs),
                               "requests": sum(r["chat_requests"] for r in rs)}
        elif j["id"] in live:
            lv = live[j["id"]]
            run_dir = pathlib.Path(lv["run_dir"]) if lv.get("run_dir") else None
            tail, last_test = _output_tail(run_dir)
            entry.update({"status": "running", "attempt": lv.get("attempt"), "phase": lv.get("phase"),
                          "elapsed": now - lv.get("started", now), "tokens": _tokens(run_dir),
                          "run_dir": str(run_dir) if run_dir else None, "tail": tail, "last_test": last_test})
        jobs.append(entry)
    return {"run_root": str(run_root), "jobs": jobs, "loaded_at": now}


def running(snapshot: dict) -> list[dict]:
    return [j for j in snapshot["jobs"] if j["status"] == "running"]


def _mmss(s) -> str:
    if s is None:
        return "--:--"
    s = int(s)
    return f"{s // 60:02d}:{s % 60:02d}"


def _job_row(j: dict, sel_id: int | None) -> str:
    mark = ">" if j["id"] == sel_id else " "
    status = j["status"] + (" (kill requested)" if j["kill_requested"] and j["status"] == "running" else "")
    tok = j["tokens"]
    tok_s = f"{tok['prompt']}/{tok['completion']}" if tok else ""
    el = _mmss(j.get("elapsed")) if j["status"] == "running" else ("" if j["status"] == "queued" else
                                                                     _mmss(j.get("wall_s")))
    att = "" if j.get("attempt") is None else str(j["attempt"])
    return (f"{mark} {j['id']:>3} {j['harness']:<10} {j['task']:<6} {j['rep']:>3}  {status:<10} "
            f"{att:>7} {el:>8} {tok_s:>14}")


def table_lines(snap: dict, sel_id: int | None, max_lines: int | None = None) -> list[str]:
    """The job table. With max_lines, only as many job rows as fit are shown, a window that keeps the selected job
    (or the first running one) visible, so the highlight never scrolls out of view."""
    jobs = snap["jobs"]
    c = {k: sum(1 for j in jobs if j["status"] == k) for k in ("queued", "running", "pass", "fail", "killed")}
    head = [f"agent-bench watch  {pathlib.Path(snap['run_root']).name}",
            f"done {c['pass'] + c['fail'] + c['killed']}/{len(jobs)}   running {c['running']}   queued {c['queued']}"
            f"   passed {c['pass']}   failed {c['fail']}   killed {c['killed']}",
            "", f"{'':1} {'#':>3} {'harness':<10} {'task':<6} {'rep':>3}  {'status':<10} {'attempt':>7} "
                f"{'elapsed':>8} {'tokens p/c':>14}"]
    foot = ["", "v view   d / a next / previous running   k kill   s settings   q quit viewer (the run keeps going)"]
    rows = [_job_row(j, sel_id) for j in jobs]
    room = len(rows) if max_lines is None else max(max_lines - len(head) - len(foot), 1)
    if room < len(rows):
        anchor = next((i for i, j in enumerate(jobs) if j["id"] == sel_id), None)
        if anchor is None:
            anchor = next((i for i, j in enumerate(jobs) if j["status"] == "running"), 0)
        start = max(0, min(anchor - room // 2, len(rows) - room))
        head[2] = f"jobs {start + 1}-{start + room} of {len(rows)}"
        rows = rows[start:start + room]
    return head + rows + foot


def view_lines(job: dict, snap: dict) -> list[str]:
    tok = job.get("tokens") or {"prompt": 0, "completion": 0, "requests": 0}
    lines = [f"Harness: {job['harness']}    Task: {job['task']}    rep {job['rep']}    attempt {job.get('attempt')}",
             f"Phase: {job.get('phase')}    Elapsed: {_mmss(job.get('elapsed'))}",
             f"Tokens this attempt (completed requests): prompt {tok['prompt']}   completion {tok['completion']}"
             f"   requests {tok['requests']}",
             f"Last test seen in output: {job.get('last_test') or 'none yet'}"
             "   (the agent may be doing something other than running it)",
             "Kill requested; waiting for the runner to stop it." if job.get("kill_requested") else "",
             "-" * 72]
    lines += job.get("tail") or ["(no output yet)"]
    lines += ["", "d next   a previous   k kill   b back to table   q quit viewer (the run keeps going)"]
    return lines


def settings_lines(values: dict, support: dict, registry: dict, mode: str, sel: int) -> list[str]:
    """Left: each setting and its value. Right: an icon for each harness that supports it.
    An icon with a '?' is declared by the adapter but not yet confirmed on the wire (run check-settings)."""
    lines = ["Settings: applied to every harness that supports them; a run uses the values in effect when it starts",
             "", f"  {'setting':<20} {'value':<10} supported by"]
    for i, s in enumerate(settingsmod.CATALOG):
        value = values.get(s.key)
        icons = []
        for name, h in registry.items():
            if s.key not in h.settings_support:
                continue
            icon = h.icon_emoji if mode == "emoji" else h.icon_ascii
            icons.append(icon if support.get(name, {}).get(s.key) else icon + "?")
        right = "  ".join(icons) if icons else "(no harness supports it)"
        mark = ">" if i == sel else " "
        lines.append(f"{mark} {s.label:<20} {'unset' if value is None else str(value):<10} {right}")
    lines += ["", "icon = confirmed on the wire    icon? = declared, not yet confirmed (agent-bench check-settings)",
              "up/down select   Enter edit   x unset   b back"]
    return lines


def request_kill(run_root: pathlib.Path, job_id: int) -> pathlib.Path:
    d = pathlib.Path(run_root) / "control"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"job-{job_id}.kill"
    f.touch()
    return f


def step(key: str, mode: str, sel: int, n_running: int) -> tuple[str, int, str | None]:
    """Pure key handling for the table and view modes. Returns (mode, selection, action)."""
    if key == "q":
        return mode, sel, "quit"
    if key in ("b", "\x1b"):
        return "table", sel, None
    if key == "s" and mode == "table":
        return "settings", sel, None
    if n_running == 0:
        return "table", 0, None
    if key == "v" and mode == "table":
        return "view", sel, None
    if key == "d":
        return mode, (sel + 1) % n_running, None
    if key == "a":
        return mode, (sel - 1) % n_running, None
    if key == "k":
        return mode, sel, "kill"
    return mode, sel, None


def _cursor(visible: int) -> None:
    """Cursor visibility is cosmetic: some terminals refuse it, and that must not stop the viewer."""
    import curses
    try:
        curses.curs_set(visible)
    except curses.error:
        pass


def run_tui(run_root: pathlib.Path | None, cfg=None) -> None:
    """Viewer for a run (run_root) and/or the settings screen (cfg). With no run, it opens on settings."""
    import curses

    from .adapter import load_registry

    registry = load_registry(cfg.harness_dir) if cfg is not None else {}
    values = dict(cfg.settings) if cfg is not None else {}
    settings_file = cfg.settings_file if cfg is not None else None

    def save_setting(stdscr, key, text):
        try:
            if text is None:
                values.pop(key, None)
            else:
                values[key] = settingsmod.parse_value(settingsmod.BY_KEY[key], text)
            settingsmod.save(settings_file, values)
            return f"saved {key}; applies to runs started from now on"
        except settingsmod.SettingsError as e:
            return f"not saved: {e}"

    def prompt(stdscr, label):
        h, w = stdscr.getmaxyx()
        curses.echo()
        _cursor(1)
        stdscr.move(h - 1, 0)
        stdscr.clrtoeol()
        stdscr.addnstr(h - 1, 0, label, max(w - 1, 1))
        stdscr.timeout(-1)                      # wait for the value; the viewer's 500 ms refresh must not cut it short
        raw = stdscr.getstr(h - 1, len(label), 24).decode(errors="replace")
        stdscr.timeout(500)
        curses.noecho()
        _cursor(0)
        return raw

    def main(stdscr):
        _cursor(0)
        stdscr.timeout(500)
        mode = "table" if run_root is not None else "settings"
        sel, sel_setting, confirm, msg = 0, 0, None, ""
        while True:
            snap = load(run_root) if run_root is not None else None
            run_now = running(snap) if snap else []
            sel = min(sel, max(len(run_now) - 1, 0))
            if mode == "view" and not run_now:
                mode = "table"
            sel_job = run_now[sel] if run_now else None
            if mode == "settings":
                mode_name = cfg.icons if cfg is not None else "emoji"
                lines = settings_lines(values, settingsmod.load_support(settings_file) if settings_file else {},
                                       registry, mode_name, sel_setting)
            elif mode == "view" and sel_job:
                lines = view_lines(sel_job, snap)
            else:
                lines = (table_lines(snap, sel_job["id"] if sel_job else None, max_lines=stdscr.getmaxyx()[0] - 2)
                         if snap else ["no run open"])
            if confirm is not None:
                lines = [f"Kill job {confirm['id']} ({confirm['harness']} {confirm['task']} rep {confirm['rep']})?"
                         " press y to confirm, any other key cancels"] + lines
            if msg:
                lines = [msg] + lines
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            for i, line in enumerate(lines[: h - 1]):
                stdscr.addnstr(i, 0, line, max(w - 1, 1))
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == -1:
                continue
            key = chr(ch) if 0 <= ch < 256 else ""
            msg = ""
            if confirm is not None:
                if key == "y":
                    request_kill(run_root, confirm["id"])
                    msg = f"kill requested for job {confirm['id']}"
                confirm = None
                continue
            if mode == "settings":
                names = [s.key for s in settingsmod.CATALOG]
                if ch == curses.KEY_UP:
                    sel_setting = (sel_setting - 1) % len(names)
                elif ch == curses.KEY_DOWN:
                    sel_setting = (sel_setting + 1) % len(names)
                elif key in ("\n", "\r"):
                    text = prompt(stdscr, f"{names[sel_setting]} (blank cancels): ")
                    if text.strip():
                        msg = save_setting(stdscr, names[sel_setting], text)
                elif key == "x":
                    msg = save_setting(stdscr, names[sel_setting], None)
                elif key in ("b", "\x1b"):
                    if run_root is not None:
                        mode = "table"
                    else:
                        return
                elif key == "q":
                    return
                continue
            if key == "q" and run_root is None:
                return
            mode, sel, action = step(key, mode, sel, len(run_now))
            if action == "quit":
                return
            if action == "kill" and run_now:
                confirm = run_now[sel]

    os.environ.setdefault("TERM", "xterm-256color")
    try:
        curses.wrapper(main)
    except curses.error as e:
        print(f"the terminal cannot run the viewer ({e}); use `agent-bench watch RUN --once` for a text table")


def print_once(run_root: pathlib.Path) -> None:
    snap = load(run_root)
    print("\n".join(table_lines(snap, None)))
