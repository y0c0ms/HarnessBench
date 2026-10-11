import importlib.util
import json
import pathlib
import textwrap
import types

import pytest

from agent_bench import config as cfgmod
from agent_bench import settings as sm
from agent_bench import settings_check
from agent_bench.watch import settings_lines

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDER = types.SimpleNamespace(model="m-1", anthropic_base_url="https://a", openai_base_url="https://o/v1")
PROXY = "http://127.0.0.1:18080"


def _plugin(name):
    path = ROOT / "harnesses" / f"{name}.py"
    if not path.exists():
        pytest.skip(f"{name} adapter is kept locally and is not in the repository")
    spec = importlib.util.spec_from_file_location(f"plug_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.HARNESS


# ---- values and file ----

@pytest.mark.parametrize("key,text,expected", [
    ("temperature", "0.2", 0.2), ("temperature", 1, 1.0), ("top_p", "0.95", 0.95),
    ("max_output_tokens", "4096", 4096), ("max_output_tokens", 512.0, 512)])
def test_valid_values_parse(key, text, expected):
    assert sm.parse_value(sm.BY_KEY[key], text) == expected


@pytest.mark.parametrize("key,text", [
    ("temperature", "3"), ("top_p", "-0.1"), ("max_output_tokens", "1.5"), ("max_output_tokens", "0"),
    ("temperature", "warm"), ("top_p", ""), ("max_output_tokens", "999999999")])
def test_invalid_values_are_rejected(key, text):
    with pytest.raises(sm.SettingsError):
        sm.parse_value(sm.BY_KEY[key], text)


def test_save_then_load_round_trips_only_set_values(tmp_path):
    f = tmp_path / "settings.toml"
    sm.save(f, {"temperature": 0.2, "max_output_tokens": 4096})
    assert sm.load(f) == {"temperature": 0.2, "max_output_tokens": 4096}
    assert "top_p" not in f.read_text()


def test_missing_file_means_no_settings(tmp_path):
    assert sm.load(tmp_path / "nope.toml") == {}


def test_unknown_key_in_file_is_an_error(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("temprature = 0.2\n")
    with pytest.raises(sm.SettingsError, match="unknown setting"):
        sm.load(f)


def test_config_loads_settings_from_its_folder_and_reports_bad_ones(tmp_path):
    (tmp_path / "settings.toml").write_text("temperature = 0.3\n")
    (tmp_path / "bench.toml").write_text(textwrap.dedent("""
        [provider]
        model = "m"
        openai_base_url = "https://x/v1"
        api_key_env = "K"
    """))
    assert cfgmod.load(tmp_path / "bench.toml").settings == {"temperature": 0.3}
    (tmp_path / "settings.toml").write_text("top_p = 7\n")
    with pytest.raises(cfgmod.ConfigError, match="between"):
        cfgmod.load(tmp_path / "bench.toml")


# ---- what each adapter writes ----

def test_pi_applies_sampling_and_output_cap(tmp_path):
    _plugin("pi").write_config(tmp_path, PROVIDER, PROXY,
                               {"temperature": 0.2, "top_p": 0.9, "max_output_tokens": 4096})
    model = json.loads((tmp_path / ".pi/agent/models.json").read_text())["providers"]["bench"]["models"][0]
    assert model["samplingParams"] == {"temperature": 0.2, "top_p": 0.9}
    assert model["maxTokens"] == 4096


def test_pi_writes_nothing_extra_when_no_settings(tmp_path):
    _plugin("pi").write_config(tmp_path, PROVIDER, PROXY, {})
    model = json.loads((tmp_path / ".pi/agent/models.json").read_text())["providers"]["bench"]["models"][0]
    assert "samplingParams" not in model and "maxTokens" not in model


def test_opencode_puts_settings_in_model_options(tmp_path):
    _plugin("opencode").write_config(tmp_path, PROVIDER, PROXY,
                                     {"temperature": 0.2, "top_p": 0.9, "max_output_tokens": 4096})
    cfg = json.loads((tmp_path / ".config/opencode/opencode.json").read_text())
    options = cfg["provider"]["bench"]["models"]["m-1"]["options"]
    assert options == {"temperature": 0.2, "top_p": 0.9, "max_tokens": 4096}


def test_omp_applies_only_the_output_cap_and_says_so(tmp_path):
    h = _plugin("omp")
    assert h.settings_support == frozenset({"max_output_tokens"})
    h.write_config(tmp_path, PROVIDER, PROXY, {"temperature": 0.2, "max_output_tokens": 4096})
    text = (tmp_path / ".omp/agent/models.yml").read_text()
    assert "maxTokens: 4096" in text and "temperature" not in text


def test_claude_applies_only_the_output_cap_via_env(tmp_path):
    h = _plugin("claude")
    assert h.settings_support == frozenset({"max_output_tokens"})
    env = h.env(tmp_path, PROXY, {"max_output_tokens": 4096, "temperature": 0.2})
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "4096"
    assert "temperature" not in " ".join(env.keys())


def test_unsupported_settings_are_ignored_not_written(tmp_path):
    _plugin("omp").write_config(tmp_path, PROVIDER, PROXY, {"temperature": 0.9, "top_p": 0.1})
    text = (tmp_path / ".omp/agent/models.yml").read_text()
    assert "temperature" not in text and "top_p" not in text and "samplingParams" not in text


# ---- the settings screen ----

class _H:
    def __init__(self, name, icon, support):
        self.name, self.icon_emoji, self.icon_ascii, self.settings_support = name, icon, icon, frozenset(support)
        self.label = name


def test_screen_shows_value_left_and_icons_right_with_confirmation_marks():
    registry = {"pi": _H("pi", "π", {"temperature", "top_p", "max_output_tokens"}),
                "omp": _H("omp", "Ω", {"max_output_tokens"})}
    support = {"pi": {"temperature": "verified"}}
    lines = settings_lines({"temperature": 0.2}, support, registry, "emoji", 0)
    temp = next(l for l in lines if "Temperature" in l)
    assert "0.2" in temp and "π" in temp and "π?" not in temp      # confirmed on the wire
    cap = next(l for l in lines if "Max output tokens" in l)
    assert "Ω?" in cap and "π?" in cap                            # declared, not yet confirmed
    assert "unset" in cap
    assert "(no harness supports it)" not in "\n".join(lines)


def test_screen_says_when_no_harness_supports_a_setting():
    lines = settings_lines({}, {}, {"omp": _H("omp", "Ω", {"max_output_tokens"})}, "ascii", 0)
    top = next(l for l in lines if "Top-p" in l)
    assert "(no harness supports it)" in top


# ---- the check: a setting counts only if the wire carried that exact value ----

def test_check_matches_exact_values_in_recorded_bodies(tmp_path):
    cap = tmp_path / "capture"
    cap.mkdir()
    (cap / "1.json").write_text(json.dumps({"path": "/v1/chat/completions", "status": 200,
                                            "body": {"temperature": 0.37, "max_completion_tokens": 777}}))
    (cap / "2.json").write_text(json.dumps({"path": "/v1/models", "status": 200,
                                            "body": {"top_p": 0.91}}))             # not a chat request: ignored
    bodies = settings_check._bodies(cap)
    assert len(bodies) == 1
    assert any(settings_check._equal(bodies[0].get(k), 0.37) for k in settings_check.BODY_KEYS["temperature"])
    assert any(settings_check._equal(bodies[0].get(k), 777) for k in settings_check.BODY_KEYS["max_output_tokens"])
    assert not any(settings_check._equal(bodies[0].get(k), 0.91) for k in settings_check.BODY_KEYS["top_p"])
    assert not any(settings_check._equal(bodies[0].get(k), 0.38) for k in settings_check.BODY_KEYS["temperature"])


def test_save_report_keeps_only_confirmed_settings(tmp_path):
    cfg = types.SimpleNamespace(settings_file=tmp_path / "settings.toml")
    support = settings_check.save_report(cfg, {"pi": {"applied": ["temperature"], "not_applied": ["top_p"],
                                                       "requests": 1, "error": None}})
    assert support == {"pi": {"temperature": "verified"}}
    assert sm.load_support(cfg.settings_file) == {"pi": {"temperature": "verified"}}
