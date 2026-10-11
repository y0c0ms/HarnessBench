import pathlib
import textwrap
import types

import pytest

from agent_bench.adapter import DUMMY_KEY, Harness, load_registry
from agent_bench.picker import tick_list

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS_DIR = ROOT / "harnesses"

PLUGIN = textwrap.dedent('''
    from agent_bench.adapter import Harness

    class Fake(Harness):
        name, label, executable, protocol = "fake", "Fake", "fake-cli", "openai"
        def write_config(self, home, provider, proxy_url, settings):
            pass
        def command(self, binary, provider, prompt):
            return [binary, prompt]

    HARNESS = Fake()
''')


def test_registry_has_only_oracle_without_plugins(tmp_path):
    assert set(load_registry(tmp_path)) == {"oracle"}
    assert set(load_registry(None)) == {"oracle"}
    assert set(load_registry(tmp_path / "missing")) == {"oracle"}


def test_plugin_file_is_registered_and_underscore_files_are_ignored(tmp_path):
    (tmp_path / "fake.py").write_text(PLUGIN)
    (tmp_path / "_draft.py").write_text("raise RuntimeError('must not be imported')")
    reg = load_registry(tmp_path)
    assert set(reg) == {"oracle", "fake"}
    assert isinstance(reg["fake"], Harness) and reg["fake"].label == "Fake"


def test_plugin_without_harness_object_is_rejected(tmp_path):
    (tmp_path / "bad.py").write_text("x = 1\n")
    with pytest.raises(ValueError, match="must define HARNESS"):
        load_registry(tmp_path)


def test_duplicate_harness_names_are_rejected(tmp_path):
    (tmp_path / "a.py").write_text(PLUGIN)
    (tmp_path / "b.py").write_text(PLUGIN)
    with pytest.raises(ValueError, match="already defined"):
        load_registry(tmp_path)


def test_template_is_inert_until_renamed():
    reg = load_registry(HARNESS_DIR)
    assert "template" not in reg          # _template.py is ignored by the loader
    assert "oracle" in reg


# ---- tick list ----

def _items(status_for_c="not found"):
    return [{"name": "a", "label": "A", "status": None},
            {"name": "b", "label": "B", "status": None},
            {"name": "c", "label": "C", "status": status_for_c}]


def _ask(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_tick_list_starts_with_preselection():
    assert tick_list(_items(), {"a", "b"}, ask=_ask([""]), show=lambda s: None) == ["a", "b"]


def test_tick_list_toggles_and_keeps_list_order():
    assert tick_list(_items(), {"a"}, ask=_ask(["2", ""]), show=lambda s: None) == ["a", "b"]
    assert tick_list(_items(), {"a", "b"}, ask=_ask(["1", ""]), show=lambda s: None) == ["b"]


def test_unavailable_harness_cannot_be_ticked():
    out = []
    picked = tick_list(_items(), {"a"}, ask=_ask(["3", ""]), show=out.append)
    assert picked == ["a"]
    assert any("unavailable" in line for line in out)


def test_all_none_and_quit():
    assert tick_list(_items(), set(), ask=_ask(["a", ""]), show=lambda s: None) == ["a", "b"]
    assert tick_list(_items(), {"a"}, ask=_ask(["n", "q"]), show=lambda s: None) == []


def test_empty_selection_asks_again_instead_of_starting():
    out = []
    picked = tick_list(_items(), set(), ask=_ask(["", "1", ""]), show=out.append)
    assert picked == ["a"]
    assert any("nothing selected" in line for line in out)


# ---- the four adapters kept in the local harness folder: their configs must never hold a real key ----

def _load_plugin(name):
    path = HARNESS_DIR / f"{name}.py"
    if not path.exists():
        pytest.skip(f"{name} adapter not present in {HARNESS_DIR}")
    return load_registry(HARNESS_DIR)[name]


PROVIDER = types.SimpleNamespace(model="m-1", anthropic_base_url="https://a", openai_base_url="https://o/v1")


@pytest.mark.parametrize("name", ["pi", "omp", "opencode"])
def test_openai_plugins_write_dummy_key_and_proxy_url(tmp_path, name):
    h = _load_plugin(name)
    h.write_config(tmp_path, PROVIDER, "http://127.0.0.1:18080", {})
    blob = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert DUMMY_KEY in blob and "127.0.0.1:18080" in blob
    assert "sk-" not in blob


def test_claude_plugin_env_carries_dummy_key_only():
    h = _load_plugin("claude")
    env = h.env(pathlib.Path("/tmp/h"), "http://127.0.0.1:18080", {})
    assert env["ANTHROPIC_AUTH_TOKEN"] == DUMMY_KEY
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:18080"
    assert h.unavailable_reason(types.SimpleNamespace(anthropic_base_url=None)) is not None
