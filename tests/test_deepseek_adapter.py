import importlib.util
import pathlib
import types

import pytest

from agent_bench.adapter import DUMMY_KEY

ADAPTER = pathlib.Path(__file__).resolve().parent.parent / "harnesses" / "deepseek.py"


def _adapter():
    if not ADAPTER.exists():
        pytest.skip("deepseek adapter is kept locally and is not in the repository")
    spec = importlib.util.spec_from_file_location("deepseek_adapter", ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.HARNESS


def test_env_points_the_sdk_at_the_proxy_with_a_dummy_key(tmp_path):
    h = _adapter()
    env = h.env(tmp_path, "http://127.0.0.1:18080", {"max_output_tokens": 2048})
    assert env["DEEPSEEK_BASE_URL"] == "http://127.0.0.1:18080/v1"
    assert env["DEEPSEEK_API_KEY"] == DUMMY_KEY
    assert env["DSH_HOME"] == str(tmp_path / ".dsh-bench")
    assert env["AGB_MAX_OUTPUT_TOKENS"] == "2048"


def test_only_the_output_cap_is_declared():
    assert _adapter().settings_support == frozenset({"max_output_tokens"})


def test_install_roots_expose_the_whole_environment(tmp_path):
    h = _adapter()
    env = tmp_path / "env"
    (env / "bin").mkdir(parents=True)
    python = env / "bin" / "python"
    python.write_text("")
    assert str(env) in h.install_roots(str(python))


def test_command_passes_prompt_and_model_to_the_script():
    h = _adapter()
    cmd = h.command("/env/bin/python", types.SimpleNamespace(model="deepseek-v4-flash"), "fix it")
    assert cmd[0] == "/env/bin/python" and cmd[-2:] == ["fix it", "deepseek-v4-flash"]
