"""Operator kills, end to end, with real sandboxes. A killed run is recorded as killed: no grading, no pass,
no fail, and it does not count toward pass rates. Skipped if bubblewrap is not installed."""
import sys
import textwrap
import threading
import time

import pytest

from agent_bench import config as cfgmod
from agent_bench import results, sandbox, tasks
from agent_bench.adapter import Harness
from agent_bench.runner import State, plan, run_all, run_one

pytestmark = pytest.mark.skipif(not sandbox.available(), reason="bubblewrap (bwrap) not installed")

STREAMING_SCRIPT = textwrap.dedent("""
    import time
    print("step one", flush=True)
    time.sleep(60)
""")


class SleepingHarness(Harness):
    """Prints a line immediately, then sleeps: long enough to kill, and it proves output is streamed."""
    name = "sleeper"
    label = "Sleeper"
    executable = "python3"
    protocol = "openai"

    def find(self, explicit):
        return sys.executable

    def write_config(self, home, provider, proxy_url, settings):
        pass

    def command(self, binary, provider, prompt):
        return [binary, "-c", STREAMING_SCRIPT]


def _cfg(tmp_path, example_tasks):
    toml = tmp_path / "bench.toml"
    toml.write_text(textwrap.dedent(f"""
        [provider]
        model = "test-model"
        openai_base_url = "http://127.0.0.1:9/v1"
        api_key_env = "AGB_TEST_KEY"
        [run]
        tasks_dir = "{example_tasks}"
        work_dir = "{tmp_path / 'runs'}"
        timeout_s = 120
    """))
    return cfgmod.load(toml)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("AGB_TEST_KEY", "sk-test-kill")


def test_kill_mid_run_is_recorded_as_killed_not_failed(tmp_path, example_tasks, key):
    cfg = _cfg(tmp_path, example_tasks)
    task = tasks.discover(example_tasks, ["title-case"])[0]
    run_root = tmp_path / "run"
    run_root.mkdir()
    kill_file = run_root / "control" / "job-0.kill"
    kill_file.parent.mkdir(parents=True)
    seen = {}

    def operator():
        time.sleep(2.5)
        seen["output_before_kill"] = (run_root / "runs" / "sleeper-title-case-r0-a0" / "harness.out").read_text()
        kill_file.touch()

    threading.Thread(target=operator, daemon=True).start()
    t0 = time.time()
    rec = run_one(cfg, task, SleepingHarness(), 0, 0, run_root, None,
                  {"job": 0, "kill_file": kill_file, "live_file": run_root / "live.json"})
    assert time.time() - t0 < 30, "the kill did not stop the harness"
    assert "step one" in seen["output_before_kill"], "output must be visible while the run is in progress"
    assert rec["killed"] is True
    assert rec["pass"] is False and rec["pytest"] == "killed by operator"
    assert rec["resources"]["processes"], "resource accounting still runs for killed sessions"
    (summary,) = results.summarise([rec])
    assert summary["killed"] == 1 and summary["attempts"] == 0 and summary["pass_rate"] is None


def test_job_killed_while_queued_never_starts_and_is_recorded(tmp_path, example_tasks, key):
    cfg = _cfg(tmp_path, example_tasks)
    cfg.reps = 1
    task = tasks.discover(example_tasks, ["title-case"])
    harness = SleepingHarness()
    run_root = tmp_path / "run"
    run_root.mkdir()
    jobs = plan(cfg, task, [harness])
    (run_root / "control").mkdir()
    (run_root / "control" / f"job-{jobs[0].id}.kill").touch()
    state = State(jobs)
    t0 = time.time()
    (rec,) = run_all(cfg, task, [harness], run_root, state, lambda m: None, jobs=jobs)
    assert time.time() - t0 < 20
    assert rec["killed"] is True and rec["wall_s"] == 0.0 and rec["chat_requests"] == 0
    assert not (run_root / "runs").exists() or not any((run_root / "runs").iterdir())
    lines = (run_root / "results.jsonl").read_text().splitlines()
    assert len(lines) == 1
