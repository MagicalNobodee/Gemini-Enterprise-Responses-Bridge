"""General-purpose local Codex multi-provider model router.

Unifies a primary OpenAI-compatible upstream and one or more secondary/local
upstreams (such as Gemini Enterprise Bridge) behind one local Codex endpoint
(default http://127.0.0.1:18001/v1). Supports exact model IDs, wildcard
patterns (e.g. "gemini-*"), per-route credential stripping, and hosted tool
filtering.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import HTTP as EMAIL_HTTP_POLICY
from fnmatch import fnmatchcase
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DEFAULT_BRIDGE_PATTERNS = ("gemini-*",)
HOP = frozenset((
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
))
STRIPPED_UPSTREAM_AUTH_HEADERS = frozenset((
    "authorization",
    "api-key",
    "x-api-key",
    "cookie",
    "chatgpt-account-id",
    "openai-organization",
    "openai-project",
    "x-target-model",
))
HOSTED_WEB_SEARCH_TOOLS = frozenset(("web_search", "web_search_preview"))
MAX_BODY_BYTES = 110 * 1024 * 1024


def load_settings(settings_path: Path | None = None) -> dict:
    path = settings_path or Path(os.environ.get("CODEX_ROUTER_SETTINGS", ROOT / "settings.json"))
    defaults = {
        "port": 18001,
        "default_timeout": 300,
    }
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            defaults.update(loaded)
    if "default_upstream" not in defaults and "original" not in defaults:
        defaults["default_upstream"] = "https://api.openai.com/v1"
    return defaults


SETTINGS = load_settings()
MODELS_PATH = Path(os.environ.get("CODEX_ROUTER_MODELS", ROOT / "models.json"))


def _normalized_routes(settings: dict | None = None) -> list[dict]:
    cfg = settings if settings is not None else SETTINGS
    explicit_routes = cfg.get("routes")
    if isinstance(explicit_routes, list) and explicit_routes:
        normalized = []
        for item in explicit_routes:
            if not isinstance(item, dict) or not item.get("upstream"):
                continue
            patterns = [str(p).strip() for p in (item.get("models") or []) if str(p).strip()]
            normalized.append({
                "name": str(item.get("name") or "custom"),
                "upstream": str(item["upstream"]).strip(),
                "models": patterns,
                "strip_auth": bool(item.get("strip_auth", True)),
                "strip_hosted_web_search": bool(item.get("strip_hosted_web_search", True)),
                "match_bridge_resources": bool(item.get("match_bridge_resources", False)),
                "timeout": int(item.get("timeout", 660)),
            })
        if normalized:
            return normalized

    # Shorthand / legacy flat configuration compatibility
    secondary_url = str(cfg.get("bridge_upstream") or cfg.get("gemini") or "http://127.0.0.1:8000/v1").strip()
    raw_patterns = cfg.get("models") or cfg.get("bridge_models") or cfg.get("gemini_models") or list(DEFAULT_BRIDGE_PATTERNS)
    patterns = [str(p).strip() for p in raw_patterns if str(p).strip()]
    return [
        {
            "name": "bridge",
            "upstream": secondary_url,
            "models": patterns,
            "strip_auth": bool(cfg.get("strip_auth", True)),
            "strip_hosted_web_search": bool(cfg.get("strip_hosted_web_search", True)),
            "match_bridge_resources": bool(cfg.get("match_bridge_resources", True)),
            "timeout": int(cfg.get("bridge_timeout", 660)),
        }
    ]


def _default_route(settings: dict | None = None) -> dict:
    cfg = settings if settings is not None else SETTINGS
    upstream = str(cfg.get("default_upstream") or cfg.get("original") or "https://api.openai.com/v1").strip()
    return {
        "name": "default",
        "upstream": upstream,
        "models": [],
        "strip_auth": False,
        "strip_hosted_web_search": False,
        "match_bridge_resources": False,
        "timeout": int(cfg.get("default_timeout", 300)),
    }


def _matches_patterns(model: str | None, patterns: list[str]) -> bool:
    if not isinstance(model, str) or not model.strip():
        return False
    base_model = model.strip().split("@", 1)[0].strip()
    return any(fnmatchcase(base_model, pat) for pat in patterns)


def _is_bridge_resource(clean_path: str, previous_response_id: str) -> bool:
    return bool(
        re.fullmatch(r"/v1/responses/resp_bridge_[0-9a-f]{32}", clean_path)
        or re.fullmatch(r"/v1/files/file_[0-9a-f]{32}(?:/content)?", clean_path)
        or re.fullmatch(r"/v1/images/files/[^/]+", clean_path)
        or (isinstance(previous_response_id, str) and re.fullmatch(r"resp_bridge_[0-9a-f]{32}", previous_response_id))
    )


def _is_json_content_type(content_type: str) -> bool:
    media = (content_type or "").split(";", 1)[0].strip().lower()
    return media in ("", "application/json") or media.endswith("+json")


def _extract_multipart_model(content_type: str, body: bytes) -> str | None:
    header_bytes = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "ignore")
    msg = BytesParser(policy=EMAIL_HTTP_POLICY).parsebytes(header_bytes + body)
    if not msg.is_multipart():
        return None
    for part in msg.iter_parts():
        if part.get_param("name", header="content-disposition") == "model" and not part.get_filename():
            val = (part.get_payload(decode=True) or b"").decode("utf-8", "replace").strip()
            return val or None
    return None


def resolve_route(
    path: str,
    body: bytes,
    content_type: str = "",
    headers=None,
    settings: dict | None = None,
) -> tuple[dict, str | None, bool]:
    parsed = urlsplit(path)
    clean_path = parsed.path
    model: str | None = None
    previous = ""
    media = (content_type or "").split(";", 1)[0].strip().lower()
    is_json = False
    if body:
        if media == "multipart/form-data":
            model = _extract_multipart_model(content_type, body)
        elif _is_json_content_type(content_type) or body.lstrip().startswith((b"{", b"[")):
            payload = json.loads(body)
            is_json = True
            if isinstance(payload, dict):
                raw_model = payload.get("model")
                model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
                previous = payload.get("previous_response_id") or ""
    if model is None and headers:
        target_hdr = headers.get("X-Target-Model") or headers.get("x-target-model")
        if target_hdr and target_hdr.strip():
            model = target_hdr.strip()
    if model is None and parsed.query:
        q_models = parse_qs(parsed.query).get("model")
        if q_models and q_models[0].strip():
            model = q_models[0].strip()

    routes = _normalized_routes(settings)
    if model is not None:
        for route in routes:
            if _matches_patterns(model, route["models"]):
                return route, model, is_json
    elif _is_bridge_resource(clean_path, previous):
        for route in routes:
            if route.get("match_bridge_resources"):
                return route, "bridge-resource", is_json

    return _default_route(settings), model, is_json


def destination(path: str, body: bytes, content_type: str = "", headers=None) -> tuple[str, str | None, bool]:
    route, model, is_json = resolve_route(path, body, content_type, headers)
    return route["upstream"], model, is_json


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, status: int, obj: dict):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"status": "ok"})
        if self.path.split("?", 1)[0] == "/v1/models":
            if MODELS_PATH.is_file():
                return self.reply(200, json.loads(MODELS_PATH.read_text(encoding="utf-8")))
            return self.reply(404, {"error": f"Model catalog not found: {MODELS_PATH}"})
        self.forward()

    def do_POST(self):
        self.forward()

    def do_DELETE(self):
        self.forward()

    def forward(self):
        started = time.monotonic()
        conn = None
        sent = False
        model = None
        try:
            if self.headers.get("Transfer-Encoding"):
                return self.reply(400, {"error": "Chunked request bodies are not supported"})
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= MAX_BODY_BYTES:
                return self.reply(413, {"error": "Request too large"})
            body = self.rfile.read(length) if length else b""
            content_type = self.headers.get("Content-Type", "")
            route, model, is_json = resolve_route(self.path, body, content_type, self.headers)
            base = route["upstream"]
            if route.get("strip_hosted_web_search") and body and is_json:
                payload = json.loads(body)
                if isinstance(payload, dict):
                    choice = payload.get("tool_choice")
                    if isinstance(choice, dict) and choice.get("type") in HOSTED_WEB_SEARCH_TOOLS:
                        return self.reply(
                            400,
                            {"error": "Hosted web search is unavailable on this route; use a local browser tool"},
                        )
                    if "tools" in payload and isinstance(payload["tools"], list):
                        payload["tools"] = [
                            t for t in payload["tools"]
                            if not (isinstance(t, dict) and t.get("type") in HOSTED_WEB_SEARCH_TOOLS)
                        ]
                    body = json.dumps(payload).encode("utf-8")

            url = urlsplit(base)
            suffix = self.path[3:] if self.path.startswith("/v1/") else self.path
            path = url.path.rstrip("/") + suffix
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            if route.get("strip_auth"):
                headers = {
                    k: v for k, v in headers.items()
                    if k.lower() not in STRIPPED_UPSTREAM_AUTH_HEADERS
                }
            headers["Connection"] = "close"

            cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
            conn = cls(url.hostname, url.port, timeout=int(route.get("timeout", 300)))
            conn.request(self.command, path, body=body or None, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status)
            for k, v in response.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            sent = True
            self.close_connection = True
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
            print(
                json.dumps({
                    "model": model,
                    "target": url.hostname,
                    "status": response.status,
                    "seconds": round(time.monotonic() - started, 2),
                }),
                flush=True,
            )
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except (ValueError, json.JSONDecodeError):
            if not sent:
                self.reply(400, {"error": "Invalid request"})
        except Exception as exc:
            print(json.dumps({"model": model, "error_type": type(exc).__name__}), flush=True)
            if not sent:
                self.reply(502, {"error": "Upstream request failed", "type": type(exc).__name__})
            self.close_connection = True
        finally:
            if conn:
                conn.close()


def main(argv: list[str] | None = None) -> None:
    global MODELS_PATH
    parser = argparse.ArgumentParser(description="Run the local Codex multi-provider model router.")
    parser.add_argument("--settings", type=Path, default=None, help="Path to settings.json")
    parser.add_argument("--models", type=Path, default=None, help="Path to merged models.json")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Override listen port")
    args = parser.parse_args(argv)
    if args.settings is not None:
        SETTINGS.clear()
        SETTINGS.update(load_settings(args.settings))
    if args.models is not None:
        MODELS_PATH = args.models
    listen_port = int(args.port if args.port is not None else SETTINGS.get("port", 18001))
    server = ThreadingHTTPServer((args.host, listen_port), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
