"""Usage accounting must count Responses API requests (Codex), not only chat-completions and messages."""
import json

from agent_bench import runner, watch


def _record(capture, path, prompt, completion):
    capture.mkdir(parents=True, exist_ok=True)
    (capture / f"{path.replace('/', '_')}.json").write_text(json.dumps({
        "path": path, "status": 200, "response_error": None,
        "usage": {"prompt": prompt, "completion": completion, "cache_read": 0, "cache_write": 0}}))


def test_responses_requests_count_as_model_requests(tmp_path):
    _record(tmp_path, "/v1/responses", 1200, 40)
    _record(tmp_path, "/v1/chat/completions", 100, 10)
    _record(tmp_path, "/v1/models", 0, 0)                       # not a model request
    u = runner._usage(tmp_path)
    assert u["chat_requests"] == 2
    assert u["prompt_tokens"] == 1300 and u["completion_tokens"] == 50


def test_viewer_live_totals_count_responses_requests(tmp_path):
    _record(tmp_path / "capture", "/v1/responses", 1200, 40)
    assert watch._tokens(tmp_path) == {"prompt": 1200, "completion": 40, "requests": 1}
