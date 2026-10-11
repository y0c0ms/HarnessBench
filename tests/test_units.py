import json
import pathlib
import textwrap

import pytest

from agent_bench import config as cfgmod
from agent_bench import judge as judgemod
from agent_bench import proxy, results, sandbox, tasks
from agent_bench.runner import State, Job


# ---------- config ----------

def _write_toml(tmp_path, text):
    p = tmp_path / "bench.toml"
    p.write_text(textwrap.dedent(text))
    return p


def test_example_config_loads(tmp_path):
    root = pathlib.Path(__file__).resolve().parent.parent / "examples"
    c = cfgmod.load(root / "bench.example.toml")
    assert c.provider.openai_base_url == "https://api.example.com/v1"
    assert c.provider.anthropic_base_url is None
    assert c.judge is None
    assert c.harnesses == []   # the tick list chooses at start
    assert c.reps == 3 and c.max_sessions == 4


def test_missing_required_key_is_reported(tmp_path):
    p = _write_toml(tmp_path, """
        [provider]
        openai_base_url = "https://x/v1"
        api_key_env = "K"
    """)
    with pytest.raises(cfgmod.ConfigError, match="model"):
        cfgmod.load(p)


def test_harness_names_are_checked_at_run_time_not_in_config(tmp_path):
    # plugins are discovered from the harness folder, so the config accepts any names; `run` checks them
    p = _write_toml(tmp_path, """
        [provider]
        model = "m"
        openai_base_url = "https://x/v1"
        api_key_env = "K"
        [run]
        harnesses = ["pi", "nope"]
    """)
    assert cfgmod.load(p).harnesses == ["pi", "nope"]


def test_relative_paths_resolve_against_config_dir(tmp_path):
    p = _write_toml(tmp_path, """
        [provider]
        model = "m"
        openai_base_url = "https://x/v1"
        api_key_env = "K"
        [run]
        tasks_dir = "my-tasks"
        work_dir = "out"
    """)
    c = cfgmod.load(p)
    assert c.tasks_dir == tmp_path / "my-tasks"
    assert c.work_dir == tmp_path / "out"


def test_judge_requires_fields_when_enabled(tmp_path):
    p = _write_toml(tmp_path, """
        [provider]
        model = "m"
        openai_base_url = "https://x/v1"
        api_key_env = "K"
        [judge]
        enabled = true
        base_url = "https://j/v1"
    """)
    with pytest.raises(cfgmod.ConfigError, match="model"):
        cfgmod.load(p)


# ---------- tasks ----------

def test_example_task_is_valid(example_tasks):
    found = tasks.discover(example_tasks, ["title-case"])
    assert [t.name for t in found] == ["title-case"]
    rep = tasks.validate(found[0], ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    assert rep["starter_fails"] and rep["reference_passes"] and rep["ok"]


def test_task_without_reference_is_not_ok(tmp_path, example_tasks):
    import shutil
    dst = tmp_path / "tasks" / "no-ref"
    shutil.copytree(example_tasks / "title-case", dst)
    shutil.rmtree(dst / "reference")
    rep = tasks.validate(tasks.discover(tmp_path / "tasks")[0], ["python3", "-m", "pytest", "-q"])
    assert rep["ok"] is True and rep["reference_passes"] is None and "cannot prove" in rep["reference"]


def test_task_missing_parts_is_reported(tmp_path):
    (tmp_path / "bad" / "starter").mkdir(parents=True)
    with pytest.raises(tasks.TaskError, match="missing"):
        tasks.discover(tmp_path)


def test_requested_task_not_found(example_tasks):
    with pytest.raises(tasks.TaskError, match="not found"):
        tasks.discover(example_tasks, ["ghost"])


# ---------- proxy ----------

def test_openai_usage_and_path_join():
    body = json.dumps({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 7}}).encode()
    assert proxy.parse_usage(body) == {"prompt": 120, "completion": 7, "cache_read": 0, "cache_write": 0}
    assert proxy.join_url("https://h/v1", "/v1/chat/completions") == "https://h/v1/chat/completions"
    assert proxy.join_url("https://h", "/v1/messages?beta=true") == "https://h/v1/messages?beta=true"


def test_anthropic_stream_counts_cached_input():
    sse = (
        'data: {"type":"message_start","message":{"usage":{"input_tokens":0,"output_tokens":0}}}\n\n'
        'data: {"type":"message_delta","usage":{"input_tokens":76,"cache_read_input_tokens":4736,'
        '"output_tokens":20}}\n\n'
    ).encode()
    u = proxy.parse_usage(sse)
    assert u["prompt"] == 4812 and u["completion"] == 20 and u["cache_read"] == 4736


def test_missing_key_env_stops_proxy(tmp_path):
    rc = proxy.main(["--sock", str(tmp_path / "s"), "--out", str(tmp_path / "o"),
                     "--openai-base", "http://x/v1", "--key-env", "AGB_DEFINITELY_UNSET_VAR"])
    assert rc == 2


# ---------- sandbox ----------

def test_install_roots_include_enclosing_node_modules(tmp_path):
    nm = tmp_path / "node_modules" / "pkg" / "bin"
    nm.mkdir(parents=True)
    exe = nm / "cli.js"
    exe.write_text("")
    roots = sandbox.install_roots(str(exe))
    assert str(tmp_path / "node_modules") in roots


def test_sandbox_argv_has_no_network_and_private_home(tmp_path):
    argv = sandbox.bwrap_argv(tmp_path / "run", tmp_path / "io", [], "/home/someone", ["true"])
    assert "--unshare-net" in argv
    assert "--tmpfs" in argv and "/home/someone" in argv


# ---------- results ----------

def test_summary_math_on_synthetic_rows():
    rows = [
        {"task": "t", "harness": "h", "rep": 0, "attempt": 0, "pass": True, "wall_s": 10, "prompt_tokens": 100,
         "completion_tokens": 10, "chat_requests": 2, "timed_out": False, "http_errors": 0, "rate_limited": 0,
         "tests_tampered": False, "error": None, "judge": {"score": 4}},
        {"task": "t", "harness": "h", "rep": 1, "attempt": 0, "pass": False, "wall_s": 30, "prompt_tokens": 300,
         "completion_tokens": 30, "chat_requests": 4, "timed_out": True, "http_errors": 1, "rate_limited": 1,
         "tests_tampered": True, "error": None, "judge": {"score": 2}},
    ]
    (s,) = results.summarise(rows)
    assert s["attempts"] == 2 and s["passes"] == 1 and s["pass_rate"] == 0.5
    assert s["mean_wall_s"] == 20 and s["mean_prompt_tokens"] == 200
    assert s["mean_judge_score"] == 3 and s["timeouts"] == 1 and s["rate_limited"] == 1 and s["tampered"] == 1


# ---------- judge ----------

def test_judge_parses_json_reply(monkeypatch, example_tasks):
    cfg = cfgmod.Judge(enabled=True, api="openai", base_url="https://j/v1", model="jm",
                       api_key_env="AGB_JUDGE_KEY", rubric=None)
    monkeypatch.setenv("AGB_JUDGE_KEY", "k")
    monkeypatch.setattr(judgemod, "_ask", lambda c, s, u: 'Sure: {"score": 5, "spec_faithful": true, '
                                                          '"minimal_change": true, "notes": "ok"}')
    t = tasks.discover(example_tasks, ["title-case"])[0]
    out = judgemod.judge_run(cfg, t, "diff", True, "4 passed")
    assert out["score"] == 5 and out["spec_faithful"] is True and out["model"] == "jm"


def test_judge_out_of_range_is_an_error_not_a_score(monkeypatch, example_tasks):
    cfg = cfgmod.Judge(enabled=True, api="openai", base_url="https://j/v1", model="jm",
                       api_key_env="AGB_JUDGE_KEY", rubric=None)
    monkeypatch.setattr(judgemod, "_ask", lambda c, s, u: '{"score": 9}')
    t = tasks.discover(example_tasks, ["title-case"])[0]
    out = judgemod.judge_run(cfg, t, "", False, "")
    assert "error" in out and "score" not in out


# ---------- progress state ----------

def test_state_counts_per_harness():
    jobs = [Job(0, "pi", "t", 0), Job(1, "pi", "t", 1), Job(2, "omp", "t", 0)]
    st = State(jobs)
    st.begin(jobs[0])
    st.end(jobs[0], {"pass": True, "wall_s": 1, "error": None})
    st.end(jobs[2], {"pass": False, "wall_s": 2, "error": "boom"})
    snap = st.snapshot()
    assert snap["done"] == 2 and snap["passed"] == 1
    assert snap["per"]["pi"]["done"] == 1 and snap["per"]["omp"]["errors"] == 1
    assert snap["running"] == {}
