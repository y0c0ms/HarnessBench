"""General settings, applied to every harness that supports them.

One file (settings.toml by default). A setting a harness does not support is not applied to it, and the settings
screen shows which harnesses support each setting. Support comes from each adapter's `settings_support`, and
`agent-bench check-settings` confirms on the wire which of those values actually reached the provider.

Settings are part of the experiment: a run records the values it used, so results stay comparable.
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import tomllib


class SettingsError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Setting:
    key: str
    label: str
    kind: str          # "float" or "int"
    lo: float
    hi: float
    help: str


CATALOG = [
    Setting("temperature", "Temperature", "float", 0.0, 2.0, "sampling temperature"),
    Setting("top_p", "Top-p", "float", 0.0, 1.0, "nucleus sampling cutoff"),
    Setting("max_output_tokens", "Max output tokens", "int", 1, 262144, "cap on tokens per model reply"),
]
BY_KEY = {s.key: s for s in CATALOG}


def parse_value(setting: Setting, text):
    if isinstance(text, str):
        text = text.strip()
        if text == "":
            raise SettingsError(f"{setting.key}: empty value (use unset to clear it)")
    try:
        number = float(text)
    except (TypeError, ValueError):
        raise SettingsError(f"{setting.key} must be a number")
    if setting.kind == "int":
        if not number.is_integer():
            raise SettingsError(f"{setting.key} must be a whole number")
        number = int(number)
    if not setting.lo <= number <= setting.hi:
        raise SettingsError(f"{setting.key} must be between {setting.lo} and {setting.hi}")
    return number


def load(path: str | pathlib.Path) -> dict:
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    try:
        raw = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{p}: {e}")
    out = {}
    for k, v in raw.items():
        if k not in BY_KEY:
            raise SettingsError(f"{p}: unknown setting '{k}'; known: {sorted(BY_KEY)}")
        out[k] = parse_value(BY_KEY[k], v)
    return out


def save(path: str | pathlib.Path, values: dict) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# General settings for agent-bench. Applied to every harness that supports them.",
             "# A run uses the values in effect when it starts."]
    for s in CATALOG:
        if s.key in values:
            lines.append(f"{s.key} = {values[s.key]}")
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(p)


def support_path(settings_file: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(settings_file).parent / "settings-support.json"


def load_support(settings_file: str | pathlib.Path) -> dict:
    """{harness: {setting: "verified"}} from the last check-settings run. Empty if never checked."""
    p = support_path(settings_file)
    return json.loads(p.read_text()) if p.exists() else {}


def save_support(settings_file: str | pathlib.Path, data: dict) -> None:
    p = support_path(settings_file)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(p)
