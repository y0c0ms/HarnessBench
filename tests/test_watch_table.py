"""Operator viewer table: on a short terminal the selected job must stay on screen and the table must fit."""
from agent_bench import watch


def _snap(n: int, running: set[int]) -> dict:
    jobs = []
    for i in range(n):
        status = "running" if i in running else ("pass" if i < min(running) else "queued")
        jobs.append({"id": i, "harness": "pi", "task": "T4", "rep": 0, "status": status, "kill_requested": False,
                     "tokens": None, "elapsed": 1.0, "wall_s": 1.0, "attempt": 0})
    return {"run_root": "/tmp/run-x", "jobs": jobs}


def test_window_fits_and_keeps_selected_job_visible():
    snap = _snap(120, running={70, 71})
    lines = watch.table_lines(snap, sel_id=70, max_lines=24)
    assert len(lines) <= 24
    assert any(line.startswith("> ") and " 70 " in line for line in lines)
    assert lines[2].startswith("jobs ")                  # the window says which jobs it shows


def test_no_window_when_everything_fits():
    snap = _snap(5, running={2})
    lines = watch.table_lines(snap, sel_id=2, max_lines=40)
    assert sum(1 for line in lines if "pi" in line) == 5
    assert not any(line.startswith("jobs ") for line in lines)
