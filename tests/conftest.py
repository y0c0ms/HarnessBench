import http.server
import json
import pathlib
import threading

import pytest

EXAMPLE_TASKS = pathlib.Path(__file__).resolve().parent.parent / "examples" / "tasks"


class MockProvider:
    """Local OpenAI- and Anthropic-compatible stand-in. Records every request so tests can check auth and paths."""

    def __init__(self):
        self.requests = []
        self.reply = "ok"
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def _send(self, code, body, ctype="application/json"):
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers), "body": None})
                self._send(200, json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode())

            def do_POST(self):
                n = int(self.headers.get("content-length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
                if self.path.startswith("/v1/messages"):
                    self._send(200, json.dumps({"id": "m", "type": "message", "role": "assistant",
                                                "content": [{"type": "text", "text": outer.reply}],
                                                "usage": {"input_tokens": 90, "cache_read_input_tokens": 30,
                                                          "output_tokens": 7}}).encode())
                else:
                    self._send(200, json.dumps({"id": "c", "object": "chat.completion",
                                                "choices": [{"index": 0, "finish_reason": "stop",
                                                             "message": {"role": "assistant", "content": outer.reply}}],
                                                "usage": {"prompt_tokens": 120, "completion_tokens": 7,
                                                          "total_tokens": 127}}).encode())

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def mock_provider():
    p = MockProvider()
    yield p
    p.close()


@pytest.fixture
def example_tasks():
    return EXAMPLE_TASKS
