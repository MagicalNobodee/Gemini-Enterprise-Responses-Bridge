"""Automated tests for codex_model_router routing, credential stripping, and installer."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import plistlib
import threading
import tomllib
from unittest.mock import patch
import urllib.request

from codex_model_router import install_router, router


def _start_server(handler_cls) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_router_splits_models_strips_credentials_and_web_search(tmp_path: Path):
    seen: list[tuple[int, str, dict, dict]] = []

    class JsonUpstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.server.server_port, self.path, dict(self.headers), json.loads(raw)))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'event: response.completed\ndata: {"type":"response.completed"}\n\n')

    models_file = tmp_path / "models.json"
    models_file.write_text(json.dumps({"models": [{"slug": "gemini-3.1-pro"}]}), encoding="utf-8")

    old_settings = dict(router.SETTINGS)
    old_models_path = router.MODELS_PATH
    orig_srv = _start_server(JsonUpstream)
    gem_srv = _start_server(JsonUpstream)
    gate_srv = _start_server(router.Handler)
    try:
        router.SETTINGS.update(
            default_upstream=f"http://127.0.0.1:{orig_srv.server_port}/v1",
            routes=[
                {
                    "name": "local-bridge",
                    "upstream": f"http://127.0.0.1:{gem_srv.server_port}/v1",
                    "models": ["gemini-*", "custom-local-model"],
                    "strip_auth": True,
                    "strip_hosted_web_search": True,
                    "match_bridge_resources": True,
                    "timeout": 660,
                }
            ],
        )
        router.MODELS_PATH = models_file

        with urllib.request.urlopen(f"http://127.0.0.1:{gate_srv.server_port}/health", timeout=5) as resp:
            assert json.loads(resp.read()) == {"status": "ok"}
        with urllib.request.urlopen(f"http://127.0.0.1:{gate_srv.server_port}/v1/models", timeout=5) as resp:
            assert json.loads(resp.read())["models"][0]["slug"] == "gemini-3.1-pro"

        orig_http = router.http.client.HTTPConnection
        timeouts: list[int] = []

        class RecordingHTTPConnection(orig_http):
            def __init__(self, *args, **kwargs):
                if kwargs.get("timeout") in (300, 660):
                    timeouts.append(kwargs["timeout"])
                super().__init__(*args, **kwargs)

        cases = [
            ("gemini-3.1-pro", gem_srv.server_port, False),
            ("custom-local-model@task-1", gem_srv.server_port, False),
            ("gpt-6.1-sol", orig_srv.server_port, True),
        ]
        with patch.object(router.http.client, "HTTPConnection", RecordingHTTPConnection):
            for model_name, expected_port, keep_auth in cases:
                payload = {
                    "model": model_name,
                    "stream": True,
                    "tools": [
                        {"type": "web_search"},
                        {"type": "web_search_preview"},
                        {"type": "function", "name": "exec_command"},
                    ],
                }
                req = urllib.request.Request(
                    f"http://127.0.0.1:{gate_srv.server_port}/v1/responses",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer sk-secret-upstream",
                        "OpenAI-Organization": "org-secret",
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    assert b"response.completed" in resp.read()
                port, path, hdrs, forwarded = seen[-1]
                assert (port, path) == (expected_port, "/v1/responses")
                lower_hdrs = {k.lower() for k in hdrs}
                assert ("authorization" in lower_hdrs) is keep_auth
                assert ("openai-organization" in lower_hdrs) is keep_auth
                assert forwarded["model"] == model_name
                assert len(forwarded["tools"]) == (3 if keep_auth else 1)
        assert timeouts == [660, 660, 300]
    finally:
        router.SETTINGS.clear()
        router.SETTINGS.update(old_settings)
        router.MODELS_PATH = old_models_path
        for srv in (orig_srv, gem_srv, gate_srv):
            srv.shutdown()
            srv.server_close()


def test_router_bridge_owned_continuations_and_multipart():
    seen: list[tuple[int, str, dict, bytes]] = []

    class RawUpstream(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append((self.server.server_port, self.path, dict(self.headers), raw))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def do_GET(self):
            seen.append((self.server.server_port, self.path, dict(self.headers), b""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        do_DELETE = do_GET

    old_settings = dict(router.SETTINGS)
    orig_srv = _start_server(RawUpstream)
    gem_srv = _start_server(RawUpstream)
    gate_srv = _start_server(router.Handler)
    resp_id = "resp_bridge_" + "a" * 32
    file_id = "file_" + "b" * 32
    boundary = "----CodexRouterBoundary99"

    def build_multipart(fields: list[tuple[str, str]]) -> bytes:
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
            for k, v in fields
        ]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\nRIFF\x00\xffWAVE\r\n--{boundary}--\r\n".encode("latin-1")
        )
        return b"".join(parts)

    try:
        router.SETTINGS.pop("default_upstream", None)
        router.SETTINGS.update(
            original=f"http://127.0.0.1:{orig_srv.server_port}/v1",
            gemini=f"http://127.0.0.1:{gem_srv.server_port}/v1",
        )
        cont_req = urllib.request.Request(
            f"http://127.0.0.1:{gate_srv.server_port}/v1/responses",
            data=json.dumps({"previous_response_id": resp_id, "input": "next"}).encode("utf-8"),
            headers={"Authorization": "Bearer SECRET", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(cont_req, timeout=5) as resp:
            assert resp.status == 200
        assert seen[-1][0] == gem_srv.server_port
        assert "authorization" not in {k.lower() for k in seen[-1][2]}

        mp_gem = build_multipart([("model", "gemini-3.1-pro")])
        mp_req = urllib.request.Request(
            f"http://127.0.0.1:{gate_srv.server_port}/v1/audio/transcriptions",
            data=mp_gem,
            headers={
                "Authorization": "Bearer SECRET",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(mp_req, timeout=5) as resp:
            assert resp.status == 200
        assert (seen[-1][0], seen[-1][1]) == (gem_srv.server_port, "/v1/audio/transcriptions")
        assert "authorization" not in {k.lower() for k in seen[-1][2]}
        assert seen[-1][3] == mp_gem

        routes = [
            (f"/v1/responses/{resp_id}", gem_srv.server_port, False),
            ("/v1/responses/resp_upstream_1", orig_srv.server_port, True),
            (f"/v1/files/{file_id}/content", gem_srv.server_port, False),
            ("/v1/images/files/gen_out.png", gem_srv.server_port, False),
            ("/v1/files/file-openai-xyz", orig_srv.server_port, True),
        ]
        for path, expected_port, keep_auth in routes:
            req = urllib.request.Request(
                f"http://127.0.0.1:{gate_srv.server_port}{path}",
                headers={"Authorization": "Bearer SECRET"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
            assert seen[-1][0] == expected_port
            assert ("authorization" in {k.lower() for k in seen[-1][2]}) is keep_auth
    finally:
        router.SETTINGS.clear()
        router.SETTINGS.update(old_settings)
        for srv in (orig_srv, gem_srv, gate_srv):
            srv.shutdown()
            srv.server_close()


def test_install_router_dry_run_and_apply_preserves_provider_secrets(tmp_path: Path, capsys):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    config_toml = codex_home / "config.toml"
    config_toml.write_text(
        'model = "gpt-6.1-sol"\n'
        'model_provider = "custom-gw"\n\n'
        "[model_providers.custom-gw]\n"
        'name = "custom-gw"\n'
        'base_url = "https://gateway.example.invalid/v1"\n'
        'experimental_bearer_token = "sk-private-do-not-touch"\n',
        encoding="utf-8",
    )
    upstream_models = tmp_path / "upstream-models.json"
    upstream_models.write_text(
        json.dumps({"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT 6.1 Sol"}]}),
        encoding="utf-8",
    )
    autostart_dir = tmp_path / "LaunchAgents"
    backup_dir = tmp_path / "backups"

    # 1. Dry-run should not write router directory or mutate config.toml
    rc = install_router.main([
        "--codex-home", str(codex_home),
        "--upstream-models", str(upstream_models),
        "--install-autostart",
        "--autostart-dir", str(autostart_dir),
    ])
    assert rc == 0
    dry_out = json.loads(capsys.readouterr().out)
    assert dry_out["applied"] is False
    assert not (codex_home / "model-router").exists()
    assert "gateway.example.invalid" in config_toml.read_text(encoding="utf-8")

    # 2. Apply writes router, settings.json, merged models.json, backup, and updates config.toml
    rc = install_router.main([
        "--codex-home", str(codex_home),
        "--upstream-models", str(upstream_models),
        "--route-models", "gemini-*,my-custom-*",
        "--catalog-models", "gemini-3.1-pro,my-custom-coder",
        "--backup-dir", str(backup_dir),
        "--install-autostart",
        "--autostart-dir", str(autostart_dir),
        "--apply",
    ])
    assert rc == 0
    apply_out = json.loads(capsys.readouterr().out)
    assert apply_out["applied"] is True
    assert backup_dir.is_dir()

    settings = json.loads((codex_home / "model-router" / "settings.json").read_text(encoding="utf-8"))
    assert settings["default_upstream"] == "https://gateway.example.invalid/v1"
    assert settings["routes"][0]["upstream"] == "http://127.0.0.1:8000/v1"
    assert settings["routes"][0]["models"] == ["gemini-*", "my-custom-*"]
    assert settings["port"] == 18001

    merged = json.loads((codex_home / "model-router" / "models.json").read_text(encoding="utf-8"))
    slugs = [m["slug"] for m in merged["models"]]
    assert "gpt-6.1-sol" in slugs
    assert "gemini-3.1-pro" in slugs
    assert "my-custom-coder" in slugs

    parsed_cfg = tomllib.loads(config_toml.read_text(encoding="utf-8"))
    gw = parsed_cfg["model_providers"]["custom-gw"]
    assert gw["base_url"] == "http://127.0.0.1:18001/v1"
    assert gw["model_catalog_url"] == "http://127.0.0.1:18001/v1/models"
    assert gw["stream_idle_timeout_ms"] == 660000
    assert gw["experimental_bearer_token"] == "sk-private-do-not-touch"

    if autostart_dir.exists():
        plist_file = autostart_dir / "local.codex-model-router.plist"
        if plist_file.is_file():
            plist_data = plistlib.loads(plist_file.read_bytes())
            assert plist_data["Label"] == "local.codex-model-router"
            assert plist_data["ProgramArguments"][1].endswith("router.py")
