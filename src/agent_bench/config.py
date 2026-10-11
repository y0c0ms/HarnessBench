"""Configuration: one TOML file. Nothing about a specific provider, host, or task set is hard-coded."""
from __future__ import annotations

import dataclasses
import pathlib
import tomllib

DEFAULT_PROMPT = (
    "Read TASK.md in the current directory and complete the task. Work only in this directory. "
    "Before you finish, run `python3 -m pytest -q` and make it pass."
)
DEFAULT_GRADE = ["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider"]


class ConfigError(ValueError):
    pass


@dataclasses.dataclass
class Provider:
    name: str
    model: str
    openai_base_url: str            # OpenAI-compatible, must serve /v1/chat/completions and /v1/models
    anthropic_base_url: str | None  # Anthropic-compatible (/v1/messages). Enables the claude harness.
    api_key_env: str                # NAME of the environment variable holding the key. The key itself is never written to disk.


@dataclasses.dataclass
class Judge:
    enabled: bool
    api: str                        # "openai" or "anthropic"
    base_url: str
    model: str
    api_key_env: str
    rubric: str | None              # path to a rubric file; default rubric is built in


@dataclasses.dataclass
class Config:
    path: pathlib.Path
    provider: Provider
    judge: Judge | None
    tasks_dir: pathlib.Path
    harness_dir: pathlib.Path       # folder of harness plugin files (one .py per harness)
    settings_file: pathlib.Path     # general settings (settings.toml), applied to every harness that supports them
    settings: dict                  # values in effect when the config was loaded; a run records them
    task_filter: list[str] | None   # None = all tasks in tasks_dir
    harnesses: list[str]
    reps: int
    max_sessions: int
    timeout_s: int
    retry_failed: int
    attempts: int                   # attempts per job, all of them (no stop-on-pass); 1 = single run
    work_dir: pathlib.Path
    prompt: str
    grade_cmd: list[str]
    keep_workspaces: bool
    icons: str                      # "emoji" or "ascii"
    binaries: dict[str, str]        # optional explicit executable per harness


def _load_settings(path: pathlib.Path) -> dict:
    from . import settings as settingsmod
    try:
        return settingsmod.load(path)
    except settingsmod.SettingsError as e:
        raise ConfigError(f"settings: {e}")


def _opt_url(v: str | None) -> str | None:
    return v.rstrip("/") if v else None


def _req(d: dict, key: str, where: str):
    if key not in d or d[key] in ("", None):
        raise ConfigError(f"{where}: missing required key '{key}'")
    return d[key]


def load(path: str | pathlib.Path) -> Config:
    path = pathlib.Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config not found: {path}")
    raw = tomllib.loads(path.read_text())
    base = path.parent

    def rel(p: str) -> pathlib.Path:
        q = pathlib.Path(p).expanduser()
        return q if q.is_absolute() else (base / q)

    p = raw.get("provider", {})
    provider = Provider(
        name=p.get("name", "provider"),
        model=_req(p, "model", "[provider]"),
        openai_base_url=_req(p, "openai_base_url", "[provider]").rstrip("/"),
        anthropic_base_url=_opt_url(p.get("anthropic_base_url")),
        api_key_env=_req(p, "api_key_env", "[provider]"),
    )

    j = raw.get("judge", {})
    judge = None
    if j.get("enabled", False):
        api = j.get("api", "openai")
        if api not in ("openai", "anthropic"):
            raise ConfigError("[judge] api must be 'openai' or 'anthropic'")
        judge = Judge(enabled=True, api=api,
                      base_url=_req(j, "base_url", "[judge]").rstrip("/"),
                      model=_req(j, "model", "[judge]"),
                      api_key_env=_req(j, "api_key_env", "[judge]"),
                      rubric=str(rel(j["rubric"])) if j.get("rubric") else None)

    r = raw.get("run", {})
    harnesses = r.get("harnesses", [])   # empty: choose at start with the tick list, or pass --harness
    tasks = r.get("tasks", ["all"])
    icons = r.get("icons", "emoji")
    if icons not in ("emoji", "ascii"):
        raise ConfigError("[tui] icons must be 'emoji' or 'ascii'")
    grade = r.get("grade_cmd", DEFAULT_GRADE)
    return Config(
        path=path,
        provider=provider,
        judge=judge,
        tasks_dir=rel(r.get("tasks_dir", "tasks")),
        harness_dir=rel(r.get("harness_dir", "harnesses")),
        settings_file=rel(r.get("settings_file", "settings.toml")),
        settings=_load_settings(rel(r.get("settings_file", "settings.toml"))),
        task_filter=None if tasks == ["all"] else list(tasks),
        harnesses=list(harnesses),
        reps=int(r.get("reps", 1)),
        max_sessions=int(r.get("max_sessions", 4)),
        timeout_s=int(r.get("timeout_s", 1500)),
        attempts=max(1, int(r.get("attempts", 1))),
        retry_failed=int(r.get("retry_failed", 0)),
        work_dir=rel(r.get("work_dir", "runs")),
        prompt=r.get("prompt", DEFAULT_PROMPT),
        grade_cmd=list(grade),
        keep_workspaces=bool(r.get("keep_workspaces", False)),
        icons=icons,
        binaries={k: str(v) for k, v in raw.get("binaries", {}).items()},
    )
