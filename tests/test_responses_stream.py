"""Streamed Responses calls (Codex): the proxy asks upstream for the complete response and streams it back as the same
output items. Function calls must survive the round trip intact."""
import http.server
import json
import threading
import urllib.request

from agent_bench import proxy

FUNCTION_CALL = {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "exec_command",
                 "arguments": "{\"cmd\": \"cat TASK.md\"}", "status": "completed"}
MESSAGE = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
           "content": [{"type": "output_text", "text": "done", "annotations": []}]}
USAGE = {"input_tokens": 8675, "output_tokens": 37, "total_tokens": 8712,
         "input_tokens_details": {"cached_tokens": 200}, "output_tokens_details": {"reasoning_tokens": 18}}


def _response(output):
    return {"id": "resp_1", "object": "response", "status": "completed", "model": "longcat-2.5-preview-free",
            "output": output, "usage": USAGE}


def _events(sse: bytes):
    out = []
    for block in sse.decode().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def test_nonstream_body_turns_streaming_off_and_keeps_the_rest():
    body = json.dumps({"model": "m", "stream": True, "input": "hi", "tools": []}).encode()
    assert json.loads(proxy.nonstream_body(body)) == {"model": "m", "stream": False, "input": "hi", "tools": []}


def test_function_call_survives_as_a_whole_output_item():
    events = _events(proxy.responses_sse(_response([FUNCTION_CALL])))
    done = [e for e in events if e["type"] == "response.output_item.done"]
    assert done[0]["item"]["name"] == "exec_command" and done[0]["item"]["arguments"] == FUNCTION_CALL["arguments"]
    args = [e for e in events if e["type"] == "response.function_call_arguments.done"]
    assert args[0]["arguments"] == FUNCTION_CALL["arguments"]
    assert events[-1]["type"] == "response.completed" and events[-1]["response"]["output"] == [FUNCTION_CALL]


def test_text_arrives_as_deltas_and_usage_is_countable():
    sse = proxy.responses_sse(_response([MESSAGE]))
    deltas = [e["delta"] for e in _events(sse) if e["type"] == "response.output_text.delta"]
    assert deltas == ["done"]
    assert proxy.parse_usage(sse) == {"prompt": 8675, "completion": 37, "cache_read": 200, "cache_write": 0}


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen = []
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _Upstream.seen.append(body)
        data = json.dumps(_response([FUNCTION_CALL])).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_proxy_streams_a_codex_call_back_from_a_complete_upstream_response(tmp_path):
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    out = tmp_path / "capture"
    out.mkdir()
    handler = proxy.make_handler(out, f"http://127.0.0.1:{upstream.server_address[1]}/v1", None, "key")
    front = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=front.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{front.server_address[1]}/v1/responses",
            data=json.dumps({"model": "m", "stream": True, "input": "hi"}).encode(),
            headers={"content-type": "application/json", "user-agent": "agent-bench"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            assert r.headers["content-type"] == "text/event-stream"
            sse = r.read()
    finally:
        front.shutdown()
        upstream.shutdown()
    assert _Upstream.seen[-1]["stream"] is False            # upstream was asked for the complete response
    assert any(e.get("item", {}).get("type") == "function_call" for e in _events(sse))
    record = json.loads(next(out.glob("*.json")).read_text())
    assert record["body"]["stream"] is True                  # the record keeps what the harness asked for
    assert record["usage"]["prompt"] == 8675 and record["usage"]["completion"] == 37
