"""Simple HTTP server that serves static files and proxies API requests."""
import http.server
import json
import os
import glob
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import urlparse, parse_qs

PORT = 9090
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(STATIC_DIR, ".api_key_cache")
PROJECTS_DIR = os.path.join(STATIC_DIR, "projects")
SKETCHES_DIR = os.path.join(STATIC_DIR, "sketches")

PROVIDERS = {
    "zhipu": {
        "name": "智谱 AI",
        "endpoint": "https://open.bigmodel.cn/api/anthropic/v1/messages",
        "format": "anthropic",
        "default_model": "glm-5.1-highspeed",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "extra_headers": {"anthropic-version": "2023-06-01"},
    },
    "openai": {
        "name": "OpenAI",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "format": "openai",
        "default_model": "gpt-4o",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "deepseek": {
        "name": "DeepSeek",
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "format": "openai",
        "default_model": "deepseek-chat",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "format": "anthropic",
        "default_model": "claude-sonnet-4-20250514",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "extra_headers": {"anthropic-version": "2023-06-01"},
    },
    "qwen": {
        "name": "通义千问",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "format": "openai",
        "default_model": "qwen-plus",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "moonshot": {
        "name": "月之暗面 Kimi",
        "endpoint": "https://api.moonshot.cn/v1/chat/completions",
        "format": "openai",
        "default_model": "moonshot-v1-8k",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "siliconflow": {
        "name": "硅基流动",
        "endpoint": "https://api.siliconflow.cn/v1/chat/completions",
        "format": "openai",
        "default_model": "Pro/deepseek-ai/DeepSeek-V3",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
    "custom": {
        "name": "自定义",
        "endpoint": "",
        "format": "openai",
        "default_model": "",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "extra_headers": {},
    },
}


def _anthropic_to_openai(body):
    """Convert Anthropic-format request body to OpenAI format."""
    messages = []
    system = body.get("system", "")
    if system:
        messages.append({"role": "system", "content": system})
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "text", "text": part.get("text", "")})
                elif part.get("type") == "image":
                    src = part.get("source", {})
                    media_type = src.get("media_type", "image/png")
                    data = src.get("data", "")
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    })
            messages.append({"role": msg["role"], "content": parts})
        else:
            messages.append({"role": msg["role"], "content": content})
    result = {
        "model": body.get("model", ""),
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
        "stream": body.get("stream", False),
        "temperature": body.get("temperature", 0.5),
    }
    return result


def _openai_to_anthropic_chunk(line):
    """Convert one OpenAI SSE data line to an Anthropic content_block_delta event."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if payload == "[DONE]":
        return None
    try:
        obj = json.loads(payload)
        delta = obj.get("choices", [{}])[0].get("delta", {})
        text = delta.get("content", "")
        if text:
            return json.dumps({
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            })
    except Exception:
        pass
    return None


def _get_provider_config():
    """Return provider config from cache, defaulting to zhipu."""
    cache = _read_cache()
    pid = cache.get("provider", "zhipu")
    cfg = PROVIDERS.get(pid, PROVIDERS["zhipu"]).copy()
    # Allow user overrides for endpoint and model
    if cache.get("endpoint") and cache["endpoint"] != "/api/messages":
        cfg["endpoint"] = cache["endpoint"]
    if cache.get("model"):
        cfg["model"] = cache["model"]
    return pid, cfg


def _read_cache():
    try:
        with open(KEY_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cache(data):
    with open(KEY_FILE, "w") as f:
        json.dump(data, f)


class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/api/cache":
            self._send_cache()
        elif self.path == "/api/providers":
            self._send_providers()
        elif self.path.startswith("/api/versions/tree"):
            self._version_tree()
        elif self.path.startswith("/api/versions/load"):
            self._version_load()
        elif self.path == "/api/sketches":
            self._sketch_list()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/messages":
            self._proxy_api()
        elif self.path == "/api/cache":
            self._save_cache()
        elif self.path == "/api/versions/save":
            self._version_save()
        elif self.path == "/api/versions/current":
            self._version_update_current()
        elif self.path == "/api/sketches/save":
            self._sketch_save()
        elif self.path == "/api/sketches/load":
            self._sketch_load()
        elif self.path == "/api/sketches/delete":
            self._sketch_delete()
        else:
            self.send_error(405)

    def _proxy_api(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        body_json = json.loads(body) if body else {}

        # Read API key from client header, fall back to cache
        api_key = self.headers.get("x-api-key", "")
        if not api_key:
            api_key = _read_cache().get("apiKey", "")

        pid, pcfg = _get_provider_config()
        is_stream = body_json.get("stream", False)
        target_fmt = pcfg["format"]

        # Build target request body
        if target_fmt == "openai":
            target_body = json.dumps(_anthropic_to_openai(body_json)).encode()
        else:
            target_body = body

        # Build target URL and headers
        target_url = pcfg["endpoint"]
        headers = {"Content-Type": "application/json"}
        auth_val = pcfg["auth_prefix"] + api_key if api_key else ""
        if auth_val:
            headers[pcfg["auth_header"]] = auth_val
        for k, v in pcfg.get("extra_headers", {}).items():
            headers[k] = v

        req = urllib.request.Request(
            target_url,
            data=target_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                if is_stream:
                    self._stream_response(resp, target_fmt)
                else:
                    if target_fmt == "openai":
                        data = self._convert_openai_response(resp.read())
                    else:
                        data = resp.read()
                    self.send_response(resp.status)
                    self.send_header("Content-Type", "application/json")
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

    def _convert_openai_response(self, raw):
        """Convert non-streaming OpenAI response to Anthropic format."""
        try:
            obj = json.loads(raw)
            text = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
            result = {
                "type": "message",
                "content": [{"type": "text", "text": text}],
                "model": obj.get("model", ""),
                "stop_reason": obj.get("choices", [{}])[0].get("finish_reason", "end_turn"),
            }
            return json.dumps(result).encode()
        except Exception:
            return raw

    def _send_providers(self):
        result = []
        for pid, cfg in PROVIDERS.items():
            result.append({
                "id": pid,
                "name": cfg["name"],
                "format": cfg["format"],
                "endpoint": cfg["endpoint"],
                "default_model": cfg["default_model"],
            })
        self._json_response(200, result)

    def _is_streaming(self, body):
        try:
            return json.loads(body).get("stream", False)
        except Exception:
            return False

    def _stream_response(self, resp, source_fmt="anthropic"):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        remainder = b""
        while True:
            chunk = resp.read(4096)
            if not chunk:
                if remainder:
                    if source_fmt == "openai":
                        self._flush_openai_chunk(remainder)
                    else:
                        self.wfile.write(remainder)
                    self.wfile.flush()
                break
            data = remainder + chunk
            lines = data.split(b"\n")
            remainder = lines[-1]
            for line in lines[:-1]:
                decoded = line.decode("utf-8", errors="replace").rstrip("\r")
                if source_fmt == "openai":
                    converted = _openai_to_anthropic_chunk(decoded)
                    if converted:
                        self.wfile.write(f"data: {converted}\n\n".encode())
                else:
                    self.wfile.write(line + b"\n")
            self.wfile.flush()

    def _flush_openai_chunk(self, data):
        """Flush remaining OpenAI SSE data."""
        decoded = data.decode("utf-8", errors="replace").rstrip("\r")
        converted = _openai_to_anthropic_chunk(decoded)
        if converted:
            self.wfile.write(f"data: {converted}\n\n".encode())

    def _send_cache(self):
        data = _read_cache()
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _save_cache(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            data = json.loads(body)
            _write_cache(data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(str(e).encode())

    # ━━━━━━ Version Management ━━━━━━
    def _json_response(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_tree(self, pname):
        """Read tree.json for a project, return None if not exists."""
        tp = os.path.join(PROJECTS_DIR, pname, "tree.json")
        if not os.path.isfile(tp):
            return None
        with open(tp, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_tree(self, pname, tree):
        """Write tree.json for a project."""
        tp = os.path.join(PROJECTS_DIR, pname, "tree.json")
        with open(tp, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)

    def _version_save(self):
        """POST /api/versions/save — save a new tree node."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        html = body.get("html", "")
        if not html:
            self._json_response(400, {"ok": False, "error": "empty html"})
            return
        label = body.get("label", "")
        pname = body.get("projectName", "")
        parent = body.get("currentNode", None)

        if not pname:
            pname = "project_" + datetime.now().strftime("%Y%m%d_%H%M%S")

        proj_dir = os.path.join(PROJECTS_DIR, pname)
        os.makedirs(proj_dir, exist_ok=True)

        tree = self._read_tree(pname)
        if not tree:
            tree = {"projectName": pname, "nodes": {}, "currentNode": None}
            parent = None  # first node has no parent

        # Assign next node id
        nid = f"n{len(tree['nodes']) + 1}"
        tree["nodes"][nid] = {
            "parent": parent,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "label": label or "初始美化",
            "instruction": body.get("instruction", ""),
        }
        tree["currentNode"] = nid

        # Save HTML file
        with open(os.path.join(proj_dir, f"{nid}.html"), "w", encoding="utf-8") as f:
            f.write(html)

        self._write_tree(pname, tree)
        self._json_response(200, {"ok": True, "nodeId": nid, "projectName": pname, "tree": tree})

    def _version_tree(self):
        """GET /api/versions/tree — return full tree."""
        qs = parse_qs(urlparse(self.path).query)
        pname = qs.get("project", [""])[0]
        if not pname:
            self._json_response(400, {"ok": False, "error": "missing project"})
            return
        tree = self._read_tree(pname)
        if not tree:
            self._json_response(200, {"ok": True, "tree": None})
            return
        self._json_response(200, {"ok": True, "tree": tree})

    def _version_load(self):
        """GET /api/versions/load?project=<name>&node=<id>"""
        qs = parse_qs(urlparse(self.path).query)
        pname = qs.get("project", [""])[0]
        nid = qs.get("node", [""])[0]
        if not pname or not nid:
            self._json_response(400, {"ok": False, "error": "missing params"})
            return

        filepath = os.path.join(PROJECTS_DIR, pname, f"{nid}.html")
        if not os.path.isfile(filepath):
            self._json_response(404, {"ok": False, "error": "not found"})
            return

        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _version_update_current(self):
        """POST /api/versions/current — update currentNode pointer."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        pname = body.get("projectName", "")
        nid = body.get("nodeId", "")
        if not pname or not nid:
            self._json_response(400, {"ok": False, "error": "missing params"})
            return
        tree = self._read_tree(pname)
        if not tree or nid not in tree.get("nodes", {}):
            self._json_response(404, {"ok": False, "error": "not found"})
            return
        tree["currentNode"] = nid
        self._write_tree(pname, tree)
        self._json_response(200, {"ok": True, "tree": tree})

    # ━━━━━━ Sketch Management ━━━━━━
    def _sketch_list(self):
        if not os.path.isdir(SKETCHES_DIR):
            self._json_response(200, {"ok": True, "sketches": []})
            return
        sketches = []
        for f in sorted(os.listdir(SKETCHES_DIR)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(SKETCHES_DIR, f), "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                ts = d.get("timestamp", "")
                name = d.get("name", f.replace(".json", ""))
                sketches.append({"name": name, "filename": f, "timestamp": ts, "thumbnail": d.get("thumbnail", "")})
            except Exception:
                continue
        sketches.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        self._json_response(200, {"ok": True, "sketches": sketches})

    def _sketch_save(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        name = body.get("name", "").strip()
        data = body.get("data", "")
        thumb = body.get("thumbnail", "")
        if not name:
            self._json_response(400, {"ok": False, "error": "missing name"})
            return
        os.makedirs(SKETCHES_DIR, exist_ok=True)
        safe_name = "".join(c for c in name if c.isalnum() or c in "._- ").strip() or "sketch"
        filename = safe_name + ".json"
        payload = {"name": name, "data": data, "thumbnail": thumb, "timestamp": datetime.now().isoformat()}
        with open(os.path.join(SKETCHES_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        self._json_response(200, {"ok": True, "filename": filename})

    def _sketch_load(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        filename = body.get("filename", "")
        if not filename:
            self._json_response(400, {"ok": False, "error": "missing filename"})
            return
        filepath = os.path.join(SKETCHES_DIR, filename)
        if not os.path.isfile(filepath):
            self._json_response(404, {"ok": False, "error": "not found"})
            return
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._json_response(200, {"ok": True, "data": data.get("data", ""), "name": data.get("name", "")})

    def _sketch_delete(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        filename = body.get("filename", "")
        if not filename:
            self._json_response(400, {"ok": False, "error": "missing filename"})
            return
        filepath = os.path.join(SKETCHES_DIR, filename)
        if os.path.isfile(filepath):
            os.remove(filepath)
        self._json_response(200, {"ok": True})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-api-key, anthropic-version, Authorization")
        self.end_headers()


if __name__ == "__main__":
    with http.server.HTTPServer(("0.0.0.0", PORT), ProxyHandler) as httpd:
        print(f"Serving on http://localhost:{PORT}")
        print(f"Supported providers: {', '.join(p['name'] for p in PROVIDERS.values())}")
        httpd.serve_forever()
