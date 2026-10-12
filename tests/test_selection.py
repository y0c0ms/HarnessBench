import types
import pathlib
import tempfile

import pytest

from agent_bench import cli, config as cfgmod, runner
from agent_bench.adapter import Harness
from agent_bench.tasks import Task


class _H(Harness):
    def __init__(self, name):
        self.name = name


def _cfg(attempts=1, retry_failed=0, reps=1, max_sessions=2):
    return types.SimpleNamespace(attempts=attempts, retry_failed=retry_failed, reps=reps, settings={},
                                 max_sessions=max_sessions, work_dir=pathlib.Path(tempfile.mkdtemp(prefix="agb-slots-")))


def _task(name):
    return Task(name=name, dir=None, description="", timeout_s=None, rubric=None)


def test_plan_restricts_to_explicit_cells():
    tasks = [_task("T7"), _task("T8")]
    hs = [_H("pi"), _H("omp")]
    jobs = runner.plan(_cfg(reps=2), tasks, hs, cells={("pi", "T7"), ("omp", "T8")})
    assert sorted((j.harness, j.task, j.rep) for j in jobs) == [
        ("omp", "T8", 0), ("omp", "T8", 1), ("pi", "T7", 0), ("pi", "T7", 1)]


def test_plan_without_cells_is_the_full_cross_product():
    jobs = runner.plan(_cfg(reps=1), [_task("T1")], [_H("pi"), _H("omp")])
    assert len(jobs) == 2


def test_parse_cells_accepts_pairs_and_rejects_typos():
    assert cli._parse_cells("pi:T7, omp:T8") == {("pi", "T7"), ("omp", "T8")}
    for bad in ("pi", "pi:", ":T7", "pi:T7:x"):
        with pytest.raises(cfgmod.ConfigError):
            cli._parse_cells(bad)


def _fake_run_one(outcomes, calls):
    def fake(cfg, task, harness, rep, attempt, run_root, judge_cfg, ctx=None):
        calls.append((harness.name, task.name, rep, attempt))
        return {"pass": outcomes[attempt % len(outcomes)], "error": None, "wall_s": 0, "killed": False,
                "harness": harness.name, "task": task.name, "rep": rep, "attempt": attempt}
    return fake


class _State:
    done, total = 0, 1
    def begin(self, job):
        pass

    def end(self, job, rec):
        pass


def test_attempts_run_every_time_even_when_passing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "run_one", _fake_run_one([True], calls))
    cfg = _cfg(attempts=3)
    runner.run_all(cfg, [_task("T7")], [_H("pi")], tmp_path, _State(), lambda m: None, jobs=None)
    assert [c[3] for c in calls] == [0, 1, 2]


def test_retry_failed_stops_on_first_pass(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runner, "run_one", _fake_run_one([False, True], calls))
    cfg = _cfg(attempts=1, retry_failed=2)
    runner.run_all(cfg, [_task("T7")], [_H("pi")], tmp_path, _State(), lambda m: None, jobs=None)
    assert [c[3] for c in calls] == [0, 1]
