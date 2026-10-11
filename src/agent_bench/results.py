"""Read run records and summarise them. Every number comes from the per-run records; nothing is estimated."""
from __future__ import annotations

import json
import pathlib
import statistics as st
from collections import defaultdict


def load(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in pathlib.Path(path).read_text().splitlines() if l.strip()]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def summarise(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["task"], r["harness"])].append(r)
    out = []
    for (task, harness), rs in sorted(groups.items()):
        rs = sorted(rs, key=lambda r: (r["rep"], r["attempt"]))
        killed = sum(1 for r in rs if r.get("killed"))
        valid = [r for r in rs if not r.get("killed")]    # an operator kill is neither a pass nor a fail
        judged = [r["judge"]["score"] for r in rs if r.get("judge") and "score" in r["judge"]]
        out.append({
            "task": task, "harness": harness,
            "attempts": len(valid), "passes": sum(r["pass"] for r in valid), "killed": killed,
            "pass_rate": (sum(r["pass"] for r in valid) / len(valid)) if valid else None,
            "first_attempt_pass": valid[0]["pass"] if valid else None,
            "mean_wall_s": _mean([r["wall_s"] for r in rs]),
            "mean_prompt_tokens": _mean([r["prompt_tokens"] for r in rs]),
            "mean_completion_tokens": _mean([r["completion_tokens"] for r in rs]),
            "mean_requests": _mean([r["chat_requests"] for r in rs]),
            "http_errors": sum(r.get("http_errors", 0) for r in rs),
            "rate_limited": sum(r.get("rate_limited", 0) for r in rs),
            "timeouts": sum(r["timed_out"] for r in rs),
            "tampered": sum(r.get("tests_tampered", False) for r in rs),
            "errors": sum(1 for r in rs if r.get("error")),
            "mean_judge_score": _mean(judged),
            "mean_cpu_s": _mean([r["resources"]["cpu_seconds"] for r in rs if r.get("resources")]),
            "mean_peak_rss_mb": _mean([r["resources"]["peak_tree_rss_mb"] for r in rs if r.get("resources")]),
        })
    return out


def process_table(rows: list[dict]) -> list[dict]:
    """Per (task, harness, process name): how many runs had it, its mean CPU seconds per run, and the largest
    resident memory it reached in any run. Runs without resource data (older records) are skipped."""
    acc: dict = {}
    for r in rows:
        res = r.get("resources")
        if not res:
            continue
        for name, g in res["processes"].items():
            a = acc.setdefault((r["task"], r["harness"], name), {"runs": 0, "cpu": 0.0, "peak": 0.0})
            a["runs"] += 1
            a["cpu"] += g["cpu_seconds"]
            a["peak"] = max(a["peak"], g["peak_rss_mb"])
    out = []
    for (task, harness, name), a in sorted(acc.items()):
        out.append({"task": task, "harness": harness, "process": name, "runs": a["runs"],
                    "mean_cpu_s": round(a["cpu"] / a["runs"], 2), "peak_rss_mb": round(a["peak"], 1)})
    return out


def markdown(rows: list[dict]) -> str:
    lines = ["| task | harness | attempts | killed | pass rate | mean wall s | mean prompt tok | mean completion tok | "
             "mean requests | judge (1-5) | mean CPU s | peak RSS MB | timeouts | rate-limited | HTTP errors | "
             "tampered | errors |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, fmt="{:.0f}": "—" if v is None else fmt.format(v)
    for s in summarise(rows):
        pr = "—" if s["pass_rate"] is None else f"{s['pass_rate']:.2f}"
        lines.append(f"| {s['task']} | {s['harness']} | {s['attempts']} | {s['killed']} | {pr} | "
                     f"{f(s['mean_wall_s'])} | {f(s['mean_prompt_tokens'])} | {f(s['mean_completion_tokens'])} | "
                     f"{f(s['mean_requests'], '{:.1f}')} | {f(s['mean_judge_score'], '{:.1f}')} | "
                     f"{f(s['mean_cpu_s'], '{:.1f}')} | {f(s['mean_peak_rss_mb'])} | {s['timeouts']} | "
                     f"{s['rate_limited']} | {s['http_errors']} | {s['tampered']} | {s['errors']} |")
    procs = process_table(rows)
    if procs:
        lines += ["", "Per process (mean CPU seconds per run; peak resident memory in any run):", "",
                  "| task | harness | process | runs | mean CPU s | peak RSS MB |", "|---|---|---|---|---|---|"]
        for p in procs:
            lines.append(f"| {p['task']} | {p['harness']} | {p['process']} | {p['runs']} | "
                         f"{p['mean_cpu_s']} | {p['peak_rss_mb']} |")
    return "\n".join(lines) + "\n"


def write_summary(run_root: pathlib.Path) -> pathlib.Path:
    rows = load(run_root / "results.jsonl")
    p = run_root / "summary.md"
    p.write_text(markdown(rows))
    (run_root / "summary.json").write_text(json.dumps({"cells": summarise(rows), "processes": process_table(rows)}, indent=2))
    return p
