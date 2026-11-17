"""Install and synchronize the local Codex multi-provider model router.

Runs in dry-run preview mode by default. Pass --apply to write files after
creating permission-locked backups of any modified configuration.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import sys
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from configure_codex_context import _safe_backup_relpath, update_catalog  # noqa: E402
from platform_compat import best_effort_chmod, reconfigure_stdio_utf8  # noqa: E402

ROUTER_DIR_SRC = Path(__file__).resolve().parent
LAUNCH_AGENT_LABEL = "local.codex-model-router"


def _is_local_loopback_port(url: str, ports: set[int]) -> bool:
    text = (url or "").strip().lower()
    for host in ("127.0.0.1", "localhost"):
        for port in ports:
            if text.startswith(f"http://{host}:{port}") or text.startswith(f"https://{host}:{port}"):
                return True
    return False


def infer_default_upstream(
    codex_home: Path,
    explicit_url: str | None,
    router_port: int,
    bridge_port: int,
) -> str:
    if explicit_url and explicit_url.strip():
        return explicit_url.strip()
    settings_file = codex_home / "model-router" / "settings.json"
    local_ports = {router_port, bridge_port}
    if settings_file.is_file():
        try:
            existing = json.loads(settings_file.read_text(encoding="utf-8"))
            orig = str(existing.get("default_upstream") or existing.get("original") or "").strip()
            if orig and not _is_local_loopback_port(orig, local_ports):
                return orig
        except Exception:
            pass
    config_file = codex_home / "config.toml"
    if config_file.is_file():
        try:
            doc = tomllib.loads(config_file.read_text(encoding="utf-8"))
            provider_name = doc.get("model_provider")
            providers = doc.get("model_providers") or {}
            if isinstance(provider_name, str) and isinstance(providers.get(provider_name), dict):
                base_url = str(providers[provider_name].get("base_url") or "").strip()
                if base_url and not _is_local_loopback_port(base_url, local_ports):
                    return base_url
        except Exception:
            pass
    return "https://api.openai.com/v1"


def build_merged_catalog(
    repo_catalog_path: Path,
    existing_router_catalog: Path | None = None,
    upstream_catalog_path: Path | None = None,
    catalog_models: list[str] | None = None,
) -> str:
    extra_doc = json.loads(update_catalog(repo_catalog_path.read_text(encoding="utf-8")))
    template_entries = [m for m in extra_doc.get("models", []) if isinstance(m, dict) and m.get("slug")]
    requested_slugs = [s.strip() for s in (catalog_models or []) if s and s.strip()]
    if requested_slugs and template_entries:
        by_slug = {m["slug"]: m for m in template_entries}
        template = template_entries[0]
        built: list[dict] = []
        for slug in requested_slugs:
            if slug in by_slug:
                built.append(copy.deepcopy(by_slug[slug]))
            else:
                cloned = copy.deepcopy(template)
                cloned["slug"] = slug
                cloned["display_name"] = slug
                built.append(cloned)
        extra_entries = built
    else:
        extra_entries = template_entries
    extra_slugs = {m["slug"] for m in extra_entries}

    base_doc: dict = {"models": []}
    source_path = upstream_catalog_path if (upstream_catalog_path and upstream_catalog_path.is_file()) else existing_router_catalog
    if source_path and source_path.is_file():
        loaded = json.loads(source_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            base_doc = dict(loaded)

    preserved = [
        m for m in base_doc.get("models", [])
        if isinstance(m, dict) and m.get("slug") not in extra_slugs
    ]
    base_doc["models"] = preserved + extra_entries
    return json.dumps(base_doc, ensure_ascii=False, indent=2) + "\n"


def _upsert_toml_key(block: str, key: str, rendered_value: str) -> str:
    pattern = rf"^{re.escape(key)}\s*=.*$"
    replacement = f"{key} = {rendered_value}"
    if re.search(pattern, block, flags=re.M):
        return re.sub(pattern, lambda _m: replacement, block, count=1, flags=re.M)
    prefix = "" if (not block or block.endswith("\n")) else "\n"
    return f"{replacement}\n{block}" if block else f"{prefix}{replacement}\n"


def update_codex_config_for_router(
    text: str,
    models_json_path: Path,
    router_port: int = 18001,
    provider_override: str | None = None,
) -> str:
    doc = tomllib.loads(text)
    provider_name = provider_override or doc.get("model_provider") or "openai-custom"
    router_base = f"http://127.0.0.1:{int(router_port)}/v1"
    router_models_url = f"{router_base}/models"

    split = re.search(r"^\[", text, flags=re.M)
    head, tail = (text[:split.start()], text[split.start():]) if split else (text, "")
    if "model_provider" not in doc:
        head = _upsert_toml_key(head, "model_provider", json.dumps(provider_name, ensure_ascii=False))
    head = _upsert_toml_key(head, "model_catalog_json", json.dumps(str(models_json_path.resolve()), ensure_ascii=False))

    table_re = re.compile(
        r"^\[model_providers\.(?:" + re.escape(provider_name) + "|" + re.escape(json.dumps(provider_name)) + r")\][^\n]*\n",
        flags=re.M,
    )
    match = table_re.search(tail)
    if match:
        next_sec = re.search(r"^\[", tail[match.end():], flags=re.M)
        sec_end = match.end() + next_sec.start() if next_sec else len(tail)
        body = tail[match.end():sec_end]
        body = _upsert_toml_key(body, "base_url", json.dumps(router_base))
        body = _upsert_toml_key(body, "model_catalog_url", json.dumps(router_models_url))
        body = _upsert_toml_key(body, "wire_api", json.dumps("responses"))
        body = _upsert_toml_key(body, "stream_idle_timeout_ms", "660000")
        tail = tail[:match.end()] + body + tail[sec_end:]
    else:
        section = (
            f"\n[model_providers.{provider_name}]\n"
            f"name = {json.dumps(provider_name)}\n"
            f"base_url = {json.dumps(router_base)}\n"
            f"model_catalog_url = {json.dumps(router_models_url)}\n"
            'wire_api = "responses"\n'
            "stream_idle_timeout_ms = 660000\n"
        )
        tail = tail.rstrip() + "\n" + section

    updated = head + tail
    tomllib.loads(updated)
    return updated


def render_macos_launch_agent(python_executable: Path, router_dir: Path) -> bytes:
    payload = {
        "KeepAlive": True,
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            str(python_executable.resolve()),
            str((router_dir / "router.py").resolve()),
        ],
        "RunAtLoad": True,
        "StandardErrorPath": str((router_dir / "router-error.log").resolve()),
        "StandardOutPath": str((router_dir / "router.log").resolve()),
        "WorkingDirectory": str(router_dir.resolve()),
    }
    return plistlib.dumps(payload, sort_keys=True)


def render_windows_startup_cmd(python_executable: Path, router_dir: Path) -> str:
    py_resolved = python_executable.resolve()
    pythonw = py_resolved.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else py_resolved
    router_py = (router_dir / "router.py").resolve()
    return f'@echo off\r\nstart "" /B "{launcher}" "{router_py}"\r\n'


def _backup_if_exists(target: Path, backup_dir: Path) -> None:
    if not target.is_file():
        return
    dest = backup_dir / _safe_backup_relpath(target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(target, dest)
        best_effort_chmod(dest, 0o600)


def _write_text_safely(target: Path, content: str, backup_dir: Path, mode: int | None = None) -> bool:
    existing = target.read_text(encoding="utf-8") if target.is_file() else None
    if existing == content:
        return False
    _backup_if_exists(target, backup_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".router-setup.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        if existing is not None and target.is_file():
            shutil.copymode(target, tmp)
        if mode is not None:
            best_effort_chmod(tmp, mode)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    reconfigure_stdio_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--default-upstream", "--original-url", dest="default_upstream", default=None,
                        help="Default upstream base URL (e.g. https://api.openai.com/v1)")
    parser.add_argument("--bridge-url", "--gemini-url", dest="bridge_url", default="http://127.0.0.1:8000/v1",
                        help="Secondary/local bridge base URL (default: http://127.0.0.1:8000/v1)")
    parser.add_argument("--route-models", default="gemini-*",
                        help="Comma-separated model IDs or glob patterns routed to --bridge-url (default: gemini-*)")
    parser.add_argument("--catalog-models", default=None,
                        help="Optional comma-separated model IDs to register in models.json (defaults to entries in --extra-models)")
    parser.add_argument("--extra-models", type=Path, default=REPO_ROOT / "codex-models.json",
                        help="Model catalog template to merge (default: codex-models.json)")
    parser.add_argument("--port", type=int, default=18001, help="Local router listen port (default: 18001)")
    parser.add_argument("--bridge-port", type=int, default=8000, help="Secondary bridge port for loop detection")
    parser.add_argument("--upstream-models", type=Path, default=None, help="Optional upstream models.json snapshot to merge")
    parser.add_argument("--provider", default=None, help="Target provider key inside config.toml")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Directory for config backups when --apply is set")
    parser.add_argument("--install-autostart", action="store_true", help="Write macOS LaunchAgent or Windows Startup launcher")
    parser.add_argument("--autostart-dir", type=Path, default=None, help="Override autostart directory (for testing)")
    parser.add_argument("--apply", action="store_true", help="Write changes to disk (default is dry-run preview)")
    args = parser.parse_args(argv)

    codex_home = args.codex_home.expanduser().resolve()
    router_dir = codex_home / "model-router"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = (
        args.backup_dir.expanduser().resolve()
        if args.backup_dir is not None
        else router_dir / "backups" / f"router-setup-{stamp}"
    )

    default_upstream = infer_default_upstream(codex_home, args.default_upstream, args.port, args.bridge_port)
    route_patterns = [p.strip() for p in args.route_models.split(",") if p.strip()] or ["gemini-*"]
    catalog_slugs = [s.strip() for s in args.catalog_models.split(",")] if args.catalog_models else None
    settings_payload = {
        "port": int(args.port),
        "default_upstream": default_upstream,
        "routes": [
            {
                "name": "local-bridge",
                "upstream": args.bridge_url.strip(),
                "models": route_patterns,
                "strip_auth": True,
                "strip_hosted_web_search": True,
                "match_bridge_resources": True,
                "timeout": 660,
            }
        ],
    }
    settings_text = json.dumps(settings_payload, ensure_ascii=False, indent=2) + "\n"
    router_code = (ROUTER_DIR_SRC / "router.py").read_text(encoding="utf-8")
    merged_models = build_merged_catalog(
        args.extra_models,
        existing_router_catalog=router_dir / "models.json",
        upstream_catalog_path=args.upstream_models,
        catalog_models=catalog_slugs,
    )

    config_path = codex_home / "config.toml"
    existing_config = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    updated_config = update_codex_config_for_router(
        existing_config,
        models_json_path=router_dir / "models.json",
        router_port=args.port,
        provider_override=args.provider,
    )

    planned: list[str] = []
    file_plan = [
        (router_dir / "router.py", router_code, None),
        (router_dir / "settings.json", settings_text, 0o600),
        (router_dir / "models.json", merged_models, None),
        (config_path, updated_config, 0o600),
    ]
    for path, content, mode in file_plan:
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != content:
            planned.append(str(path))
            if args.apply:
                backup_dir.mkdir(parents=True, exist_ok=True)
                best_effort_chmod(backup_dir, 0o700)
                _write_text_safely(path, content, backup_dir, mode=mode)

    autostart_target: Path | None = None
    if args.install_autostart:
        if sys.platform == "darwin" or (args.autostart_dir is not None and os.name != "nt"):
            plist_dir = args.autostart_dir or (Path.home() / "Library" / "LaunchAgents")
            autostart_target = plist_dir / f"{LAUNCH_AGENT_LABEL}.plist"
            plist_bytes = render_macos_launch_agent(Path(sys.executable), router_dir)
            if not autostart_target.is_file() or autostart_target.read_bytes() != plist_bytes:
                planned.append(str(autostart_target))
                if args.apply:
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    best_effort_chmod(backup_dir, 0o700)
                    _backup_if_exists(autostart_target, backup_dir)
                    autostart_target.parent.mkdir(parents=True, exist_ok=True)
                    autostart_target.write_bytes(plist_bytes)
        elif os.name == "nt":
            startup_dir = args.autostart_dir or (
                Path(os.environ.get("APPDATA", Path.home()))
                / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            )
            autostart_target = startup_dir / "CodexModelRouter.cmd"
            cmd_text = render_windows_startup_cmd(Path(sys.executable), router_dir)
            if not autostart_target.is_file() or autostart_target.read_text(encoding="utf-8") != cmd_text:
                planned.append(str(autostart_target))
                if args.apply:
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    _write_text_safely(autostart_target, cmd_text, backup_dir)

    summary = {
        "applied": bool(args.apply),
        "router_dir": str(router_dir),
        "router_listen": f"http://127.0.0.1:{int(args.port)}/v1",
        "bridge_upstream": args.bridge_url.strip(),
        "route_models": route_patterns,
        "default_upstream_configured": bool(default_upstream),
        "backup_dir": str(backup_dir) if (args.apply and planned) else None,
        "changed_files": planned,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
