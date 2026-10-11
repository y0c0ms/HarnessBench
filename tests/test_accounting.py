import json

from agent_bench.runner import _usage


def _rec(d, name, status, body, response_error=None):
    (d / f"{name}.json").write_text(json.dumps({
        "path": "/v1/chat/completions", "status": status, "body": body, "response_error": response_error,
        "usage": {"prompt": 10, "completion": 2, "cache_read": 0, "cache_write": 0}}))


def test_rate_limit_phrase_in_request_body_is_not_a_rate_limit(tmp_path):
    # a harness's own system prompt may quote the phrase; a 200 response is not throttling
    _rec(tmp_path, "a", 200, {"messages": [{"role": "system", "content": "implement rate limiting"}]})
    u = _usage(tmp_path)
    assert u["rate_limited"] == 0 and u["http_errors"] == 0 and u["chat_requests"] == 1


def test_429_and_error_envelopes_count_as_rate_limits(tmp_path):
    _rec(tmp_path, "a", 429, {}, response_error="too many requests")
    _rec(tmp_path, "b", 200, {}, response_error='{"message": "Rate limit exceeded"}')
    _rec(tmp_path, "c", 500, {}, response_error="boom")
    u = _usage(tmp_path)
    assert u["rate_limited"] == 2 and u["http_errors"] == 2
