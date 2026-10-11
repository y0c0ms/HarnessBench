"""Per-run logging proxy. Runs on the host, outside the sandbox.

Listens on a unix socket. Every request is forwarded to the configured provider with the REAL key injected
(inbound auth headers from the harness are discarded), and one JSON record per request is written to OUT_DIR:
request body, status, and token usage. The harness never sees the provider key.

    python -m agent_bench.proxy --sock S --out DIR --openai-base URL [--anthropic-base URL] --key-env NAME
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import pathlib
import socketserver
import sys
import time
import urllib.error
import urllib.request

SKIP_REQ_HEADERS = ("host", "content-length", "authorization", "x-api-key", "accept-encoding", "connection")


def _objects(data: bytes) -> list[dict]:
    text = data.decode("utf-8", "replace")
    objs = []
    if text.lstrip().startswith("{"):
        try:
            objs.append(json.loads(text))
        except Exception:
            pass
    else:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    objs.append(json.loads(line[5:].strip()))
                except Exception:
                    pass
    return [o for o in objs if isinstance(o, dict)]


def parse_usage(data: bytes) -> dict:
    """Total prompt tokens (cached input included), completion tokens, and the cache split.

    OpenAI: prompt_tokens already includes cached tokens.
    Anthropic: input_tokens excludes cache reads/writes, so the prompt total is their sum.
    Anthropic streams report input in message_start (often 0) and the final count in message_delta:
    the last non-null value seen wins."""
    openai_prompt = None
    inp = out = cache_read = cache_write = None
    for o in _objects(data):
        for u in (o.get("usage"), (o.get("message") or {}).get("usage")):
            if not isinstance(u, dict):
                continue
            if u.get("prompt_tokens") is not None:
                openai_prompt = u["prompt_tokens"]
            if u.get("completion_tokens") is not None:
                out = u["completion_tokens"]
            if u.get("input_tokens") is not None:
                inp = u["input_tokens"]
            if u.get("output_tokens") is not None:
                out = u["output_tokens"]
            if u.get("cache_read_input_tokens") is not None:
                cache_read = u["cache_read_input_tokens"]
            if u.get("cache_creation_input_tokens") is not None:
                cache_write = u["cache_creation_input_tokens"]
    if openai_prompt is not None:
        prompt = openai_prompt
    else:
        prompt = (inp or 0) + (cache_read or 0) + (cache_write or 0)
    return {"prompt": prompt, "completion": out or 0,
            "cache_read": cache_read or 0, "cache_write": cache_write or 0}


def join_url(base: str, path: str) -> str:
    """Join a provider base URL and a harness request path without doubling '/v1'."""
    if path.startswith("/v1") and base.endswith("/v1"):
        return base + path[3:]
    return base + path


def make_handler(out_dir: pathlib.Path, openai_base: str, anthropic_base: str | None, key: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def _forward(self):
            n = int(self.headers.get("content-length", 0) or 0)
            body = self.rfile.read(n) if n else b""
            try:
                req_body = json.loads(body) if body else None
            except Exception:
                req_body = {"raw": body.decode("utf-8", "replace")[:2000]}
            is_anthropic = self.path.startswith("/v1/messages")
            if is_anthropic:
                if not anthropic_base:
                    self._reply(404, b'{"error":"no anthropic upstream configured"}', "application/json")
                    return
                upstream = join_url(anthropic_base, self.path)
            else:
                upstream = join_url(openai_base, self.path)
            req = urllib.request.Request(upstream, data=body or None, method=self.command)
            for k, v in self.headers.items():
                if k.lower() not in SKIP_REQ_HEADERS:
                    req.add_header(k, v)
            if is_anthropic:
                req.add_header("x-api-key", key)
            else:
                req.add_header("Authorization", f"Bearer {key}")
            try:
                r = urllib.request.urlopen(req, timeout=900)
                code, data = r.status, r.read()
                ct = r.headers.get("content-type", "application/json")
            except urllib.error.HTTPError as e:
                code, data, ct = e.code, e.read(), "application/json"
            except Exception as e:  # upstream unreachable: the harness gets a clean error, the record shows it
                code, data, ct = 502, json.dumps({"error": f"upstream: {e}"}).encode(), "application/json"
            response_error = None
            if code != 200:
                response_error = data[:500].decode("utf-8", "replace")
            else:
                try:
                    obj = json.loads(data)
                    if isinstance(obj, dict) and "error" in obj:   # some gateways return errors with HTTP 200
                        response_error = json.dumps(obj["error"])[:500]
                except Exception:
                    pass
            rec = {"path": self.path, "t": time.time(), "status": code,
                   "user_agent": self.headers.get("user-agent", ""), "body": req_body,
                   "response_error": response_error,
                   "usage": parse_usage(data) if code == 200 else {"prompt": 0, "completion": 0}}
            (out_dir / f"{time.time_ns()}.json").write_text(json.dumps(rec))
            self._reply(code, data, ct)

        def _reply(self, code, data, ct):
            self.send_response(code)
            self.send_header("content-type", ct)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = _forward
        do_GET = _forward

        def log_message(self, *a):
            pass

    return Handler


class UnixThreadingServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sock", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--openai-base", required=True)
    ap.add_argument("--anthropic-base", default=None)
    ap.add_argument("--key-env", required=True)
    a = ap.parse_args(argv)
    key = os.environ.get(a.key_env)
    if not key:
        print(f"environment variable {a.key_env} is not set", file=sys.stderr)
        return 2
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    handler = make_handler(out, a.openai_base.rstrip("/"), (a.anthropic_base or None) and a.anthropic_base.rstrip("/"), key)
    UnixThreadingServer(a.sock, handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
