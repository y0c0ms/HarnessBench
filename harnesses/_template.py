"""Template for a harness plugin. Copy to harnesses/<name>.py (no leading underscore), then fill in the blanks.

It appears in the start-up tick list under its `name`. Nothing else in the project needs to change.

Checklist:
  1. Set name (unique, used in config and results), label (display), icons, executable (what `which` finds),
     and protocol: "openai" if the CLI speaks OpenAI-compatible chat completions, "anthropic" for /v1/messages.
  2. write_config(): write whatever config file the CLI reads, under `home`, pointing at `proxy_url` with
     DUMMY_KEY as the key. Never write a real key here.
  3. settings_support: declare only the general settings you apply in write_config/env (temperature, top_p,
     max_output_tokens). Then run `agent-bench check-settings` to confirm they reach the provider.
  4. env(): point the CLI's config and data directories into `home` (the base class already does HOME and XDG).
  5. command(): the argv to run. The prompt is passed in; the model is provider.model.
  6. Run `agent-bench run --harness <name> --task <one-task> --reps 1` and check the record in results.jsonl.
"""
import json
import pathlib

from agent_bench.adapter import DUMMY_KEY, Harness


class Template(Harness):
    name = "template"              # rename, e.g. "codex" or "deepseek"
    label = "Template"             # shown in the display
    icon_emoji = "◆"
    icon_ascii = "tp"
    executable = "template-cli"    # the program that must be on PATH (or set [binaries] template-cli)
    protocol = "openai"
    settings_support = frozenset()  # e.g. frozenset({"temperature", "max_output_tokens"}) once applied and checked

    def write_config(self, home: pathlib.Path, provider, proxy_url: str, settings: dict) -> None:
        d = home / ".config/template-cli"
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps({
            "baseUrl": proxy_url + "/v1", "apiKey": DUMMY_KEY, "model": provider.model}, indent=2))

    def command(self, binary: str, provider, prompt: str) -> list[str]:
        return [binary, "--model", provider.model, prompt]


HARNESS = Template()
