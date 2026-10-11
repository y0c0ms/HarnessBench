"""Optional LLM judge. Runs after grading and adds a qualitative score; the tests stay the primary result.

It sees the task, the change the agent made (a diff against the starter), and the test outcome. It returns
JSON: {"score": 1-5, "spec_faithful": bool, "minimal_change": bool, "notes": str}.
Any provider works: the judge config names an OpenAI-compatible or Anthropic-compatible endpoint and an
environment variable holding its key. No model name or endpoint is assumed."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_RUBRIC = """You are reviewing a coding agent's change to a repository.
Judge only what is in the task, the diff, and the test outcome.
- score (1-5): 5 = correct, minimal, idiomatic, and fully satisfies the task text; 3 = works but is
  over-broad, fragile, or misses a stated rule; 1 = wrong or unrelated.
- spec_faithful: does the change implement what the task text says, including edge cases it lists?
- minimal_change: were only the necessary files and lines changed?
Reply with one JSON object and nothing else:
{"score": <1-5>, "spec_faithful": <true|false>, "minimal_change": <true|false>, "notes": "<one or two sentences>"}"""

MAX_DIFF_CHARS = 60_000


def _post(url: str, headers: dict, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _ask(cfg, system: str, user: str) -> str:
    key = os.environ.get(cfg.api_key_env)
    if not key:
        raise RuntimeError(f"judge key variable {cfg.api_key_env} is not set")
    if cfg.api == "anthropic":
        d = _post(cfg.base_url + "/v1/messages",
                  {"x-api-key": key, "anthropic-version": "2023-06-01"},
                  {"model": cfg.model, "max_tokens": 1024, "system": system,
                   "messages": [{"role": "user", "content": user}]})
        return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    d = _post(cfg.base_url + "/chat/completions", {"Authorization": f"Bearer {key}"},
              {"model": cfg.model, "max_tokens": 1024,
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    return d["choices"][0]["message"]["content"]


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in judge reply")
    obj = json.loads(m.group(0))
    score = int(obj["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"score out of range: {score}")
    return {"score": score, "spec_faithful": bool(obj.get("spec_faithful")),
            "minimal_change": bool(obj.get("minimal_change")), "notes": str(obj.get("notes", ""))[:500]}


def judge_run(cfg, task, diff: str, passed: bool, test_summary: str) -> dict:
    rubric = task.rubric or (open(cfg.rubric).read() if cfg.rubric else DEFAULT_RUBRIC)
    task_text = (task.dir / "TASK.md").read_text()
    shown = diff if len(diff) <= MAX_DIFF_CHARS else diff[:MAX_DIFF_CHARS] + "\n[diff truncated]"
    user = (f"## Task\n{task_text}\n\n## Test outcome\n{'PASS' if passed else 'FAIL'}: {test_summary}\n\n"
            f"## Change made by the agent (unified diff against the starter)\n```diff\n{shown or '(no change)'}\n```")
    try:
        return {"model": cfg.model, **_parse(_ask(cfg, rubric, user))}
    except (urllib.error.URLError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as e:
        return {"model": cfg.model, "error": f"{type(e).__name__}: {e}"}
