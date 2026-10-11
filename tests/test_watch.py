import json
import pathlib

from agent_bench import watch


def _make_run(root: pathlib.Path) -> pathlib.Path:
    run = root / "run"
    (run / "live").mkdir(parents=True)
    (run / "control").mkdir()
    plan = [{"id": 0, "harness": "pi", "task": "T7", "rep": 0},
            {"id": 1, "harness": "omp", "task": "T7", "rep": 0},
            {"id": 2, "harness": "claude", "task": "T8", "rep": 0},
            {"id": 3, "harness": "opencode", "task": "T9", "rep": 0}]
    (run / "plan.json").write_text(json.dumps(plan))
    usage = {"prompt_tokens": 40, "completion_tokens": 9, "chat_requests": 2}
    done = [{"harness": "pi", "task": "T7", "rep": 0, "attempt": 0, "pass": True, "wall_s": 120.0,
             "killed": False, **usage},
            {"harness": "omp", "task": "T7", "rep": 0, "attempt": 0, "pass": False, "wall_s": 5.0,
             "killed": True, **usage}]
    (run / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in done))
    attempt = root / "attempt"
    (attempt / "capture").mkdir(parents=True)
    (attempt / "harness.out").write_text("working on sched\nrunning test_sched.py::test_dom_or_dow now\n")
    for i, (p, c) in enumerate([(1000, 200), (1500, 300)]):
        (attempt / "capture" / f"{i}.json").write_text(json.dumps(
            {"path": "/v1/chat/completions", "status": 200, "usage": {"prompt": p, "completion": c,
                                                                       "cache_read": 0, "cache_write": 0}}))
    (run / "live" / "job-2.json").write_text(json.dumps(
        {"job": 2, "harness": "claude", "task": "T8", "rep": 0, "attempt": 0, "phase": "harness",
         "started": 0.0, "run_dir": str(attempt)}))
    return run


def test_load_classifies_jobs_and_reads_running_session(tmp_path):
    snap = watch.load(_make_run(tmp_path))
    by_id = {j["id"]: j for j in snap["jobs"]}
    assert by_id[0]["status"] == "pass" and by_id[0]["wall_s"] == 120.0
    assert by_id[1]["status"] == "killed"
    assert by_id[2]["status"] == "running"
    assert by_id[3]["status"] == "queued"


def test_running_session_shows_tokens_last_test_and_output(tmp_path):
    snap = watch.load(_make_run(tmp_path))
    job = {j["id"]: j for j in snap["jobs"]}[2]
    assert job["tokens"] == {"prompt": 2500, "completion": 500, "requests": 2}
    assert job["last_test"] == "test_sched.py::test_dom_or_dow"
    lines = watch.view_lines(job, snap)
    text = "\n".join(lines)
    assert "Harness: claude" in text and "Task: T8" in text
    assert "prompt 2500" in text and "completion 500" in text
    assert "test_sched.py::test_dom_or_dow" in text
    assert "working on sched" in text


def test_table_shows_every_job_with_status_and_totals(tmp_path):
    snap = watch.load(_make_run(tmp_path))
    text = "\n".join(watch.table_lines(snap, sel_id=2))
    assert "passed 1" in text and "killed 1" in text and "running 1" in text and "queued 1" in text
    assert "> " in text and "claude" in text


def test_step_moves_between_running_jobs_and_handles_kill_and_back():
    assert watch.step("v", "table", 0, 2) == ("view", 0, None)
    assert watch.step("d", "view", 0, 2) == ("view", 1, None)
    assert watch.step("d", "view", 1, 2) == ("view", 0, None)          # wraps around
    assert watch.step("a", "view", 0, 2) == ("view", 1, None)          # previous wraps too
    assert watch.step("k", "view", 1, 2) == ("view", 1, "kill")
    assert watch.step("b", "view", 1, 2) == ("table", 1, None)
    assert watch.step("q", "table", 0, 2) == ("table", 0, "quit")
    assert watch.step("v", "table", 0, 0) == ("table", 0, None)        # nothing running: no view


def test_request_kill_writes_the_control_file(tmp_path):
    run = _make_run(tmp_path)
    f = watch.request_kill(run, 2)
    assert f == run / "control" / "job-2.kill" and f.exists()
    snap = watch.load(run)
    assert {j["id"]: j for j in snap["jobs"]}[2]["kill_requested"] is True
