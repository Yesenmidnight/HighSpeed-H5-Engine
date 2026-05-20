"""Simple HTTP server that serves static files and proxies API requests."""
import http.server
import json
import os
import urllib.request
import urllib.error

PORT = 9090
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
API_TARGET = "https://open.bigmodel.cn/api/anthropic/v1/messages"


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_POST(self):
        if self.path == "/api/messages":
            self._proxy_api()
        else:
            self.send_error(405)

    def _proxy_api(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        req = urllib.request.Request(
            API_TARGET,
            data=body,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # Forward x-api-key and anthropic-version from client
        for hdr in ("x-api-key", "anthropic-version"):
            val = self.headers.get(hdr)
            if val:
                req.add_header(hdr, val)

        try:
            with urllib.request.urlopen(req) as resp:
                is_stream = self._is_streaming(body)

                if is_stream:
                    self._stream_response(resp)
                else:
                    data = resp.read()
                    self.send_response(resp.status)
                    for hdr in ("content-type",):
                        v = resp.getheader(hdr)
                        if v:
                            self.send_header(hdr, v)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(data)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(str(e).encode())

    def _is_streaming(self, body):
        try:
            return json.loads(body).get("stream", False)
        except Exception:
            return False

    def _stream_response(self, resp):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        while True:
            line = resp.readline()
            if not line:
                break
            self.wfile.write(line)
            self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key, anthropic-version")
        self.end_headers()

    def end_headers(self):
        if not any(h[0].lower() == "access-control-allow-origin" for h in self._headers_buffer if isinstance(h, tuple)):
            pass  # already set by caller
        super().end_headers()


if __name__ == "__main__":
    with http.server.HTTPServer(("0.0.0.0", PORT), ProxyHandler) as httpd:
        print(f"Serving on http://localhost:{PORT}")
        print(f"API proxy: /api/messages -> {API_TARGET}")
        httpd.serve_forever()
