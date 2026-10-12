import json

from agent_bench.runner import _usage


def _rec(d, name, status, body, response_error=None, served=None):
    (d / f"{name}.json").write_text(json.dumps({
        "path": "/v1/chat/completions", "status": status, "body": body, "response_error": response_error,
        "served_model": served,
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


def test_served_models_names_the_model_the_provider_reported(tmp_path):
    # the ledger cross-check: a run states which model served it, and flags a gateway that moved it mid-run
    _rec(tmp_path, "a", 200, {}, served="longcat-free")
    _rec(tmp_path, "b", 200, {}, served="longcat-free")
    assert _usage(tmp_path)["served_models"] == "longcat-free"
    _rec(tmp_path, "c", 200, {}, served="claude-haiku-5-5")
    assert _usage(tmp_path)["served_models"] == "claude-haiku-5-5,longcat-free"


def test_served_models_is_none_when_the_upstream_says_nothing(tmp_path):
    _rec(tmp_path, "a", 200, {})
    assert _usage(tmp_path)["served_models"] is None
