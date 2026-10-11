"""End-to-end checks with real bubblewrap sandboxes, a real logging proxy, and a local mock provider.
No external network is used. Skipped automatically when bwrap is not installed."""
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid

import pytest

from agent_bench import config as cfgmod
from agent_bench import sandbox, tasks
from agent_bench.adapter import Harness
from agent_bench.runner import run_one

pytestmark = pytest.mark.skipif(not sandbox.available(), reason="bubblewrap (bwrap) not installed")

REAL_KEY = "sk-test-REAL-KEY-do-not-leak"
RELAY = f"http://127.0.0.1:{sandbox.RELAY_PORT}"


def _wait_for(path: pathlib.Path, proc, limit=10):
    for _ in range(int(limit / 0.05)):
        if path.exists() or proc.poll() is not None:
            return
        time.sleep(0.05)


@pytest.fixture
def proxy_env(monkeypatch):
    monkeypatch.setenv("AGB_TEST_KEY", REAL_KEY)
    return "AGB_TEST_KEY"


def _start_proxy(sock, out, upstream, key_env):
    return subprocess.Popen(
        [sys.executable, "-m", "agent_bench.proxy", "--sock", str(sock), "--out", str(out),
         "--openai-base", upstream + "/v1", "--key-env", key_env],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)


def test_sandbox_exit_is_only_the_proxy(mock_provider, proxy_env, tmp_path):
    run = tmp_path / "run"
    (run / "home").mkdir(parents=True)
    (run / "ws").mkdir()
    io = pathlib.Path(tempfile.mkdtemp(prefix="agb-test-io-", dir="/tmp"))
    cap = tmp_path / "cap"
    proxy = _start_proxy(io / "proxy.sock", cap, mock_provider.url, proxy_env)
    _wait_for(io / "proxy.sock", proxy)
    host_canary = pathlib.Path("/tmp") / f"agb-host-canary-{uuid.uuid4().hex}"
    host_canary.write_text("host only")
    home_canary = pathlib.Path.home() / f".agb-home-canary-{uuid.uuid4().hex}"
    home_canary.write_text("real home only")
    try:
        script = textwrap.dedent(f"""
            import json, os, pathlib, urllib.request, urllib.error
            out = {{}}
            try:
                urllib.request.urlopen("{mock_provider.url}/v1/models", timeout=5); out["direct_provider"] = "REACHABLE"
            except Exception as e:
                out["direct_provider"] = "blocked"
            req = urllib.request.Request("{RELAY}/v1/chat/completions", headers={{"content-type": "application/json",
                  "authorization": "Bearer agb-local-dummy"}},
                  data=json.dumps({{"model": "m", "messages": [{{"role": "user", "content": "hi"}}]}}).encode())
            out["via_relay"] = json.loads(urllib.request.urlopen(req, timeout=30).read())["choices"][0]["message"]["content"]
            out["host_tmp_visible"] = os.path.exists("{host_canary}")
            out["real_home_visible"] = os.path.exists("{home_canary}")
            out["real_key_in_env"] = any("{REAL_KEY}" in v for v in os.environ.values())
            pathlib.Path("result.json").write_text(json.dumps(out))
        """)
        inner = (f"{sys.executable} {sandbox.RELAY_PATH} {sandbox.RELAY_PORT} {sandbox.IO_DIR}/proxy.sock "
                 f"& sleep 0.5; exec {sys.executable} -c {shlex.quote(script)}")
        argv = sandbox.bwrap_argv(run, io, sandbox.install_roots(sys.executable),
                                  os.path.expanduser("~"), ["sh", "-c", inner])
        p = subprocess.run(argv, cwd=run / "ws", capture_output=True, text=True, timeout=120,
                           env={"PATH": "/usr/bin:/bin", "HOME": str(run / "home")})
        assert p.returncode == 0, p.stderr[-800:]
        out = json.loads((run / "ws" / "result.json").read_text())
        assert out["direct_provider"] == "blocked"
        assert out["via_relay"] == "ok"
        assert out["host_tmp_visible"] is False
        assert out["real_home_visible"] is False
        assert out["real_key_in_env"] is False
        # the provider saw the REAL key, injected by the proxy, not the harness's dummy
        seen = [r for r in mock_provider.requests if r["path"].startswith("/v1/chat")]
        assert seen and seen[-1]["headers"].get("Authorization") == f"Bearer {REAL_KEY}"
        # and the proxy recorded the usage of that call
        recs = [json.loads(f.read_text()) for f in cap.glob("*.json")]
        assert any(r["usage"]["prompt"] == 120 and r["usage"]["completion"] == 7 for r in recs)
    finally:
        proxy.terminate()
        host_canary.unlink(missing_ok=True)
        home_canary.unlink(missing_ok=True)
        shutil.rmtree(io, ignore_errors=True)


FIX = textwrap.dedent('''
    def title_case(s):
        out, start = [], True
        for ch in s:
            if ch.isspace():
                out.append(ch); start = True
            else:
                out.append(ch.upper() if start else ch); start = False
        return "".join(out)
''')


class ScriptedHarness(Harness):
    """A stand-in model harness: calls the provider through the relay, writes a fix, optionally tampers with tests."""
    name = "scripted"
    label = "Scripted"
    executable = "python3"
    protocol = "openai"

    def __init__(self, tamper=False):
        self.tamper = tamper

    def find(self, explicit):
        return sys.executable

    def write_config(self, home, provider, proxy_url, settings):
        pass

    def command(self, binary, provider, prompt):
        tamper = "pathlib.Path('test_textutil.py').write_text('def test_x():\\n    assert True\\n')" \
            if self.tamper else "pass"
        body = textwrap.dedent(f"""
            import json, pathlib, urllib.request
            req = urllib.request.Request("{RELAY}/v1/chat/completions",
                  data=json.dumps({{"model": "m", "messages": [{{"role": "user", "content": "fix it"}}]}}).encode(),
                  headers={{"content-type": "application/json", "authorization": "Bearer agb-local-dummy"}})
            json.loads(urllib.request.urlopen(req, timeout=30).read())
            pathlib.Path('textutil.py').write_text({FIX!r})
            {tamper}
        """)
        return [binary, "-c", body]


def _cfg(tmp_path, upstream, tasks_dir, keep=True):
    toml = tmp_path / "bench.toml"
    toml.write_text(textwrap.dedent(f"""
        [provider]
        name = "mock"
        model = "test-model"
        openai_base_url = "{upstream}/v1"
        api_key_env = "AGB_TEST_KEY"
        [run]
        tasks_dir = "{tasks_dir}"
        work_dir = "{tmp_path / 'runs'}"
        keep_workspaces = {'true' if keep else 'false'}
        timeout_s = 120
    """))
    return cfgmod.load(toml)


def test_full_run_records_pass_usage_and_diff(mock_provider, proxy_env, tmp_path, example_tasks):
    cfg = _cfg(tmp_path, mock_provider.url, example_tasks)
    task = tasks.discover(example_tasks, ["title-case"])[0]
    run_root = tmp_path / "run"
    run_root.mkdir()
    rec = run_one(cfg, task, ScriptedHarness(), 0, 0, run_root, None)
    assert rec["error"] is None, rec
    assert rec["pass"] is True, rec["pytest"]
    assert rec["chat_requests"] == 1 and rec["prompt_tokens"] == 120 and rec["completion_tokens"] == 7
    assert rec["tests_tampered"] is False
    diff = (pathlib.Path(rec["run_dir"]) / "change.diff").read_text()
    assert "textutil.py" in diff and "+    out, start = [], True" in diff
    assert rec["http_errors"] == 0


def test_tampered_tests_are_restored_and_flagged(mock_provider, proxy_env, tmp_path, example_tasks):
    cfg = _cfg(tmp_path, mock_provider.url, example_tasks)
    task = tasks.discover(example_tasks, ["title-case"])[0]
    run_root = tmp_path / "run"
    run_root.mkdir()
    rec = run_one(cfg, task, ScriptedHarness(tamper=True), 0, 0, run_root, None)
    assert rec["tests_tampered"] is True
    # tests were restored before grading, so the real tests decide the result
    assert rec["pass"] is True
    restored = (pathlib.Path(rec["run_dir"]) / "ws" / "test_textutil.py").read_text()
    assert "test_basic" in restored


def test_missing_provider_key_is_an_error_record(mock_provider, tmp_path, example_tasks, monkeypatch):
    monkeypatch.delenv("AGB_TEST_KEY", raising=False)
    cfg = _cfg(tmp_path, mock_provider.url, example_tasks, keep=False)
    task = tasks.discover(example_tasks, ["title-case"])[0]
    run_root = tmp_path / "run"
    run_root.mkdir()
    rec = run_one(cfg, task, ScriptedHarness(), 0, 0, run_root, None)
    assert rec["error"] and "logging proxy failed" in rec["error"]
    assert rec["pass"] is False
