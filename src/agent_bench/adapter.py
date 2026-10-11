"""Harness adapter interface and plugin loading.

The core ships no agent adapters. A harness is a plugin: one Python file in the project's harness folder
(default `harnesses/`) that defines a module-level `HARNESS` object (an instance of a Harness subclass).
Files whose name starts with an underscore are ignored, so `_template.py` can serve as a starting point.

Each adapter answers four questions:
  - which executable to look for, and which API protocol it speaks ("openai", "anthropic", or None)
  - what config files to write into the run's private HOME so it talks to the logging proxy
  - what environment and command line to launch it with
  - whether it needs a model at all

The provider's real key is never given to a harness. Each config carries a dummy key; the proxy injects the real one.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil

DUMMY_KEY = "agb-local-dummy"   # sent by the harness; the proxy replaces it with the real key


class Harness:
    name = ""
    label = ""
    icon_emoji = "•"
    icon_ascii = "*"
    executable = ""
    protocol = "openai"          # "openai", "anthropic", or None
    needs_model = True
    settings_support: frozenset = frozenset()   # general settings this harness can apply (see settings.py)

    def find(self, explicit: str | None) -> str | None:
        """Return the executable to run, or None. `explicit` is the [binaries] override from the config."""
        if explicit:
            return explicit if pathlib.Path(explicit).exists() else None
        found = shutil.which(self.executable)
        if found and os.path.basename(os.path.realpath(found)) == "snap":
            # a snap launcher cannot run inside the sandbox; use the snap's real executable instead
            real = f"/snap/{self.executable}/current/bin/{self.executable}"
            return real if os.path.exists(real) else found
        return found

    def unavailable_reason(self, provider) -> str | None:
        if self.protocol == "anthropic" and not getattr(provider, "anthropic_base_url", None):
            return "needs provider.anthropic_base_url (Anthropic-compatible endpoint)"
        return None

    def write_config(self, home: pathlib.Path, provider, proxy_url: str, settings: dict) -> None:
        """Write this harness's config files under the private HOME. Must not contain the provider key.
        `settings` holds the values in effect (only the keys set); apply those in settings_support, ignore the rest."""
        raise NotImplementedError

    def env(self, home: pathlib.Path, proxy_url: str, settings: dict) -> dict:
        return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_DATA_HOME": str(home / ".local/share"), "XDG_CACHE_HOME": str(home / ".cache"),
                "XDG_STATE_HOME": str(home / ".local/state"), "LANG": "C.UTF-8", "TERM": "dumb"}

    def command(self, binary: str, provider, prompt: str) -> list[str]:
        raise NotImplementedError


class Oracle(Harness):
    """Built-in self-test: applies the task's reference solution. No model, no network, no sandbox."""
    name, label, icon_emoji, icon_ascii, executable, protocol = "oracle", "Oracle", "✓", "or", "", None
    needs_model = False

    def find(self, explicit):
        return "oracle"


def _load_file(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"agb_harness_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    h = getattr(mod, "HARNESS", None)
    if not isinstance(h, Harness) or not h.name:
        raise ValueError(f"{path}: must define HARNESS = <Harness subclass instance> with a non-empty name")
    return h


def load_registry(harness_dir: pathlib.Path | None) -> dict[str, Harness]:
    """Built-in adapters plus every plugin file in harness_dir. Duplicate names are an error."""
    reg: dict[str, Harness] = {"oracle": Oracle()}
    if harness_dir is None or not pathlib.Path(harness_dir).is_dir():
        return reg
    for path in sorted(pathlib.Path(harness_dir).glob("*.py")):
        if path.name.startswith("_"):
            continue
        h = _load_file(path)
        if h.name in reg:
            raise ValueError(f"harness name '{h.name}' from {path} is already defined")
        reg[h.name] = h
    return reg


__all__ = ["Harness", "Oracle", "DUMMY_KEY", "load_registry"]
