#!/usr/bin/env python3
"""The Margin — local server. Standard library only, no build step.

Serves index.html and proxies /api/sample to the Anthropic messages
endpoint, streaming the SSE back untouched so the page can render prose
as it is written.

    export ANTHROPIC_API_KEY=sk-ant-...
    python3 serve.py            # http://127.0.0.1:7878

Environment overrides:
    MARGIN_PORT     default 7878
    MARGIN_QUICK    model for the Brisk tier
    MARGIN_DEFAULT  model for the Considered tier
    MARGIN_COMPLEX  model for the outline call
"""
import json, os, pathlib, sys, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).parent
API = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = int(os.environ.get("MARGIN_MAX_TOKENS", "4096"))

MODELS = {
    "quick":   os.environ.get("MARGIN_QUICK",   "claude-haiku-4-5-20251001"),
    "default": os.environ.get("MARGIN_DEFAULT", "claude-sonnet-5"),
    "complex": os.environ.get("MARGIN_COMPLEX", "claude-opus-5"),
}

KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def auth_headers():
    """Console keys authenticate with x-api-key; OAuth access tokens
    (sk-ant-oat..., the kind Claude Code issues) authenticate with a bearer
    header and are rejected outright by x-api-key. Pick by prefix."""
    head = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if KEY.startswith("sk-ant-oat"):
        head["authorization"] = "Bearer " + KEY
    else:
        head["x-api-key"] = KEY
    return head



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # ---------- page ----------
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/index.html"):
            return self.send_error(404, "no such page")
        page = HERE / "index.html"
        if not page.exists():
            return self.send_error(500, "index.html is missing - run patch.py first")
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- proxy ----------
    def do_POST(self):
        if self.path != "/api/sample":
            return self.send_error(404, "no such endpoint")
        if not KEY:
            return self.send_error(401, "ANTHROPIC_API_KEY is not set in the server environment")

        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self.send_error(400, "bad request body: %s" % e)

        messages = req.get("messages") or []
        if not isinstance(messages, list) or not messages:
            return self.send_error(400, "no messages")
        model = MODELS.get(req.get("tier") or "default", MODELS["default"])

        payload = json.dumps({
            "model": model,
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "messages": messages,
        }).encode("utf-8")

        up = urllib.request.Request(API, data=payload, method="POST", headers=auth_headers())

        try:
            stream = urllib.request.urlopen(up, timeout=300)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:600]
            return self.send_error(e.code, detail)
        except Exception as e:
            return self.send_error(502, "upstream unreachable: %s" % e)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                chunk = stream.read(1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass          # the reader hit Stop, or turned back; nothing to do
        finally:
            stream.close()
        self.close_connection = True


def main():
    port = int(os.environ.get("MARGIN_PORT", "7878"))
    if not KEY:
        print("! ANTHROPIC_API_KEY is not set - the page will load but no turn will write.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...\n")
    print("The Margin  ->  http://127.0.0.1:%d" % port)
    print("  brisk      %s" % MODELS["quick"])
    print("  considered %s" % MODELS["default"])
    print("  outline    %s" % MODELS["complex"])
    print("  ctrl-c to stop\n")
    try:
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
