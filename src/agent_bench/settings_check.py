"""Confirms, on the wire, which general settings each harness actually applies.

One tiny probe task per harness, run through the normal isolated runner with known values for every setting. The
proxy records each request body; a setting counts as applied only if a recorded request carries that exact value.
Results are saved next to the settings file, and the settings screen shows them (confirmed icons vs icon?).
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import time

from . import settings as settingsmod
from .runner import run_one
from .tasks import discover

PROBE = {"temperature": 0.37, "top_p": 0.91, "max_output_tokens": 777}
BODY_KEYS = {"temperature": ("temperature",), "top_p": ("top_p",),
             "max_output_tokens": ("max_tokens", "max_completion_tokens", "max_output_tokens")}
PROBE_PROMPT = "Reply with the single word: ok. Do not change any files."


def _make_probe_task(root: pathlib.Path):
    d = root / "probe"
    (d / "starter").mkdir(parents=True)
    (d / "tests").mkdir()
    (d / "TASK.md").write_text(PROBE_PROMPT + "\n")
    (d / "starter" / "probe.py").write_text("X = 1\n")
    (d / "tests" / "test_probe.py").write_text("from probe import X\n\n\ndef test_probe():\n    assert X == 1\n")
    return discover(root)[0]


def _bodies(capture: pathlib.Path) -> list[dict]:
    out = []
    for f in capture.glob("*.json"):
        d = json.loads(f.read_text())
        if ("/chat/completions" in d["path"] or "/messages" in d["path"]) and isinstance(d.get("body"), dict):
            out.append(d["body"])
    return out


def _equal(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and abs(float(a) - float(b)) < 1e-9
    return a == b


def check(cfg, harnesses) -> dict:
    """Runs one probe per runnable harness. Returns {harness: {applied, not_applied, requests, reached, error}}.
    The probe lives under the work directory, like real runs: some harnesses unpack large files into HOME, which
    fails on a small /tmp."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = pathlib.Path(cfg.work_dir) / "settings-probe" / stamp
    root.mkdir(parents=True, exist_ok=True)
    task = _make_probe_task(root)
    probe_cfg = dataclasses.replace(cfg, settings=dict(PROBE), prompt=PROBE_PROMPT, attempts=1,
                                    retry_failed=0, timeout_s=300, keep_workspaces=False)
    run_root = root / "run"
    run_root.mkdir()
    report = {}
    for h in harnesses:
        if not h.needs_model:
            continue
        rec = run_one(probe_cfg, task, h, 0, 0, run_root, None, None)
        bodies = _bodies(pathlib.Path(rec["run_dir"]) / "capture")
        applied, missing = [], []
        for key, value in PROBE.items():
            if key not in h.settings_support:
                continue
            seen = any(_equal(b.get(k), value) for b in bodies for k in BODY_KEYS[key])
            (applied if seen else missing).append(key)
        reached = rec["chat_requests"] > 0
        # a harness that never reached the provider says nothing about the settings: report that, not "not applied"
        report[h.name] = {"applied": applied if reached else [], "not_applied": missing if reached else [],
                          "requests": rec["chat_requests"], "reached": reached,
                          "error": rec["error"] or (None if reached else
                                                    f"no request reached the provider (exit {rec['exit']}; "
                                                    f"see {rec['run_dir']}/harness.err)")}
    return report


def save_report(cfg, report: dict) -> dict:
    """Store confirmed settings next to the settings file. A harness keeps only what was confirmed now."""
    support = {name: {k: "verified" for k in r["applied"]} for name, r in report.items()}
    settingsmod.save_support(cfg.settings_file, support)
    return support
