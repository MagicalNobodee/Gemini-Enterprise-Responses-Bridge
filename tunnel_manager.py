"""Managed free public tunnel controller (Cloudflare Quick Tunnel / Named Tunnel & reachability probe)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from platform_compat import (
    IS_WINDOWS,
    atomic_write_json,
    best_effort_chmod,
    find_executable,
    is_pid_alive,
    subprocess_hidden_kwargs,
    terminate_pid_gracefully,
)

logger = logging.getLogger("gemini_bridge.tunnel")

_TRYCLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)
_POSIX_CLOUDFLARED_PATHS = (
    "/opt/homebrew/bin/cloudflared",
    "/usr/local/bin/cloudflared",
    "/usr/bin/cloudflared",
)
_WINDOWS_CLOUDFLARED_PATHS = (
    r"%ProgramFiles%\cloudflared\cloudflared.exe",
    r"%ProgramFiles(x86)%\cloudflared\cloudflared.exe",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe",
    r"%USERPROFILE%\scoop\shims\cloudflared.exe",
    r"%ProgramData%\chocolatey\bin\cloudflared.exe",
    r"C:\cloudflared\cloudflared.exe",
)
_POSIX_TAILSCALE_PATHS = (
    "/opt/homebrew/bin/tailscale",
    "/usr/local/bin/tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
)
_WINDOWS_TAILSCALE_PATHS = (
    r"%ProgramFiles%\Tailscale\tailscale.exe",
    r"%ProgramFiles(x86)%\Tailscale\tailscale.exe",
    r"%LOCALAPPDATA%\Tailscale\tailscale.exe",
)


def find_cloudflared_binary() -> Optional[str]:
    return find_executable(
        "cloudflared",
        posix_candidates=_POSIX_CLOUDFLARED_PATHS,
        windows_candidates=_WINDOWS_CLOUDFLARED_PATHS,
    )


def find_tailscale_binary() -> Optional[str]:
    return find_executable(
        "tailscale",
        posix_candidates=_POSIX_TAILSCALE_PATHS,
        windows_candidates=_WINDOWS_TAILSCALE_PATHS,
    )


def _is_cloudflared_pid_alive(pid: int) -> bool:
    return is_pid_alive(pid, expected_name_substr="cloudflared")


def _normalize_https_origin(raw: str) -> str:
    cleaned = (raw or "").strip().rstrip("/")
    if cleaned.endswith("/v1"):
        cleaned = cleaned[:-3].rstrip("/")
    return cleaned


class PublicTunnelManager:
    """Manages a local cloudflared process and verifies external public reachability."""

    def __init__(
        self,
        *,
        target_port: int = 8000,
        state_path: Optional[str | Path] = None,
        on_url_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.target_port = int(target_port)
        self._state_path = Path(state_path) if state_path else None
        self._log_path = (
            self._state_path.with_name("cloudflared_tunnel.log")
            if self._state_path is not None
            else Path(tempfile.gettempdir()) / f"geb_cloudflared_{self.target_port}.log"
        )
        self._on_url_changed = on_url_changed
        self._lock = threading.RLock()

        self.mode: str = "quick"  # quick | named
        self.auto_sync_public_url: bool = True
        self.named_tunnel_token: str = ""
        self.named_public_url: str = ""

        self._pid: int = 0
        self._active_url: str = ""
        self._started_at: int = 0
        self._last_error: str = ""
        self._last_probe: Optional[Dict[str, Any]] = None

        if self._state_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Persistence & Process Adoption
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._state_path is None or not self._state_path.is_file():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取隧道状态文件失败 (%s): %s", self._state_path, exc)
            return
        if not isinstance(raw, dict):
            return
        if raw.get("mode") in {"quick", "named"}:
            self.mode = str(raw["mode"])
        if "auto_sync_public_url" in raw:
            self.auto_sync_public_url = bool(raw["auto_sync_public_url"])
        if isinstance(raw.get("named_tunnel_token"), str):
            self.named_tunnel_token = raw["named_tunnel_token"].strip()
        if isinstance(raw.get("named_public_url"), str):
            self.named_public_url = _normalize_https_origin(raw["named_public_url"])

        saved_pid = int(raw.get("pid") or 0)
        saved_port = int(raw.get("target_port") or self.target_port)
        if saved_pid > 0 and saved_port == self.target_port and _is_cloudflared_pid_alive(saved_pid):
            self._pid = saved_pid
            self._active_url = _normalize_https_origin(str(raw.get("active_url") or ""))
            self._started_at = int(raw.get("started_at") or time.time())
            if not self._active_url and self.mode == "quick":
                self._active_url = self._scan_log_for_quick_url()

    def _save_locked(self) -> None:
        if self._state_path is None:
            return
        payload = {
            "version": 1,
            "updated_at": int(time.time()),
            "target_port": self.target_port,
            "mode": self.mode,
            "auto_sync_public_url": self.auto_sync_public_url,
            "named_tunnel_token": self.named_tunnel_token,
            "named_public_url": self.named_public_url,
            "pid": self._pid,
            "active_url": self._active_url,
            "started_at": self._started_at,
        }
        try:
            atomic_write_json(self._state_path, payload, mode=0o600, dir_mode=0o700)
        except Exception as exc:
            logger.warning("保存隧道状态文件失败 (%s): %s", self._state_path, exc)

    def _scan_log_for_quick_url(self) -> str:
        if not self._log_path.is_file():
            return ""
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="ignore")
            matches = _TRYCLOUDFLARE_URL_RE.findall(text)
            return matches[-1] if matches else ""
        except Exception:
            return ""

    def _tail_log_lines(self, max_lines: int = 12) -> list[str]:
        if not self._log_path.is_file():
            return []
        try:
            lines = self._log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            return [ln.strip() for ln in lines if ln.strip()][-max_lines:]
        except Exception:
            return []

    def _refresh_runtime_locked(self) -> None:
        if self._pid > 0 and not _is_cloudflared_pid_alive(self._pid):
            self._pid = 0
            if self.mode == "quick":
                self._active_url = ""
            if not self._last_error:
                self._last_error = "公网隧道进程已退出，可点击一键重新开启。"
            self._save_locked()
        elif self._pid > 0 and self.mode == "quick" and not self._active_url:
            discovered = self._scan_log_for_quick_url()
            if discovered:
                self._active_url = discovered
                self._save_locked()
                if self.auto_sync_public_url and self._on_url_changed:
                    try:
                        self._on_url_changed(discovered)
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    # Lifecycle Controls
    # ------------------------------------------------------------------

    def stop(self, *, clear_public_url: bool = False) -> Dict[str, Any]:
        with self._lock:
            pid = self._pid
            self._pid = 0
            self._active_url = ""
            self._started_at = 0
            self._last_error = ""
            self._save_locked()

        if pid > 0 and _is_cloudflared_pid_alive(pid):
            terminate_pid_gracefully(pid, timeout_sec=2.5, expected_name_substr="cloudflared")

        if clear_public_url and self._on_url_changed:
            try:
                self._on_url_changed("")
            except Exception:
                pass
        return self.snapshot()

    async def start(
        self,
        *,
        mode: Optional[str] = None,
        named_tunnel_token: Optional[str] = None,
        named_public_url: Optional[str] = None,
        auto_sync_public_url: Optional[bool] = None,
        restart: bool = False,
        wait_seconds: float = 14.0,
    ) -> Dict[str, Any]:
        bin_path = find_cloudflared_binary()
        if not bin_path:
            install_cmd = (
                "winget install --id Cloudflare.cloudflared"
                if IS_WINDOWS
                else "brew install cloudflared"
            )
            raise RuntimeError(
                f"本机未检测到 cloudflared 工具。请先在终端执行 `{install_cmd}` 后再试。"
            )

        with self._lock:
            self._refresh_runtime_locked()
            if mode in {"quick", "named"}:
                self.mode = mode
            if named_tunnel_token is not None:
                t_clean = named_tunnel_token.strip()
                if t_clean:
                    self.named_tunnel_token = t_clean
            if named_public_url is not None:
                self.named_public_url = _normalize_https_origin(named_public_url)
            if auto_sync_public_url is not None:
                self.auto_sync_public_url = bool(auto_sync_public_url)

            if self.mode == "named" and not self.named_tunnel_token:
                raise ValueError("固定域名模式需要填写 Cloudflare Tunnel Token（如无域名请使用免登录免费模式）。")

            if self._pid > 0 and not restart:
                if self.mode == "quick" and self._active_url:
                    return self.snapshot()
                if self.mode == "named":
                    return self.snapshot()

        # Stop existing tunnel process cleanly before spawning a new one
        await asyncio.to_thread(self.stop, clear_public_url=False)

        with self._lock:
            self._log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.mode == "named":
                cmd = [
                    bin_path,
                    "tunnel",
                    "--no-autoupdate",
                    "--protocol",
                    "http2",
                    "run",
                    "--token",
                    self.named_tunnel_token,
                ]
            else:
                cmd = [
                    bin_path,
                    "tunnel",
                    "--no-autoupdate",
                    "--protocol",
                    "http2",
                    "--url",
                    f"http://127.0.0.1:{self.target_port}",
                ]

            log_fh = open(self._log_path, "w", encoding="utf-8")
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    **subprocess_hidden_kwargs(detached=True),
                )
            finally:
                log_fh.close()
            best_effort_chmod(self._log_path, 0o600)

            self._pid = int(proc.pid)
            self._started_at = int(time.time())
            self._last_error = ""
            self._active_url = self.named_public_url if self.mode == "named" else ""
            self._save_locked()

        if self.mode == "quick":
            deadline = time.monotonic() + max(2.0, float(wait_seconds))
            discovered = ""
            while time.monotonic() < deadline:
                if not _is_cloudflared_pid_alive(self._pid):
                    break
                discovered = self._scan_log_for_quick_url()
                if discovered:
                    break
                await asyncio.sleep(0.25)

            with self._lock:
                if discovered:
                    self._active_url = discovered
                    self._last_error = ""
                    self._save_locked()
                    if self.auto_sync_public_url and self._on_url_changed:
                        try:
                            self._on_url_changed(discovered)
                        except Exception:
                            pass
                elif not _is_cloudflared_pid_alive(self._pid):
                    self._pid = 0
                    tail = " | ".join(self._tail_log_lines(4))
                    self._last_error = f"隧道启动失败：{tail or '请检查本机网络连接'}"
                    self._save_locked()
                    raise RuntimeError(self._last_error)
        else:
            await asyncio.sleep(1.2)
            with self._lock:
                if not _is_cloudflared_pid_alive(self._pid):
                    self._pid = 0
                    tail = " | ".join(self._tail_log_lines(4))
                    self._last_error = f"固定域名隧道启动失败：{tail or '请检查 Tunnel Token 是否正确'}"
                    self._save_locked()
                    raise RuntimeError(self._last_error)
                if self.named_public_url and self.auto_sync_public_url and self._on_url_changed:
                    try:
                        self._on_url_changed(self.named_public_url)
                    except Exception:
                        pass

        return self.snapshot()

    # ------------------------------------------------------------------
    # End-to-End Public Reachability Self-Test
    # ------------------------------------------------------------------

    async def probe_public_reachability(
        self,
        public_url: Optional[str] = None,
        *,
        sample_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            self._refresh_runtime_locked()
            target_base = _normalize_https_origin(public_url or self._active_url or self.named_public_url)
        if not target_base:
            raise ValueError("当前没有可检测的公网地址，请先开启免费公网通道或填写公网域名。")
        if not (target_base.startswith("https://") or target_base.startswith("http://")):
            target_base = "https://" + target_base

        def _sync_probe() -> Dict[str, Any]:
            ctx = ssl.create_default_context()
            ua = "GeminiEnterpriseBridge-Probe/1.0"
            t0 = time.perf_counter()

            # 1) Health check (retry briefly if trycloudflare DNS is still warming up)
            health_ok = False
            health_status = 0
            health_body: Dict[str, Any] = {}
            last_exc = ""
            for attempt in range(4):
                req_h = urllib.request.Request(
                    f"{target_base}/health",
                    headers={"User-Agent": ua, "Accept": "application/json"},
                    method="GET",
                )
                try:
                    with urllib.request.urlopen(req_h, timeout=8.0, context=ctx) as resp:
                        health_status = int(resp.status)
                        raw = resp.read().decode("utf-8", errors="ignore")
                        health_body = json.loads(raw) if raw.strip().startswith("{") else {}
                        if health_status == 200 and health_body.get("status") == "ok":
                            health_ok = True
                            break
                except urllib.error.HTTPError as he:
                    health_status = int(he.code)
                    last_exc = f"HTTP {he.code}"
                    if he.code in {502, 503, 530} and attempt < 3:
                        time.sleep(1.2)
                        continue
                    break
                except Exception as exc:
                    last_exc = str(exc)
                    if attempt < 3:
                        time.sleep(1.2)
                        continue
            latency_ms = int((time.perf_counter() - t0) * 1000)

            if not health_ok:
                return {
                    "ok": False,
                    "tested_at": int(time.time()),
                    "public_url": target_base,
                    "latency_ms": latency_ms,
                    "health_ok": False,
                    "auth_lock_verified": False,
                    "admin_lock_verified": False,
                    "client_key_verified": None,
                    "detail": f"公网地址暂未连通（{last_exc or ('HTTP ' + str(health_status))}）。若刚开启隧道，请等 3 秒后再测。",
                }

            # 2) Verify keyless public request is blocked with 401/403
            auth_lock_ok = False
            req_unauth = urllib.request.Request(
                f"{target_base}/v1/models",
                headers={"User-Agent": ua, "Accept": "application/json"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req_unauth, timeout=8.0, context=ctx) as resp:
                    auth_lock_ok = int(resp.status) in {401, 403}
            except urllib.error.HTTPError as he:
                auth_lock_ok = int(he.code) in {401, 403}
            except Exception:
                auth_lock_ok = False

            # 3) Verify admin console is strictly blocked from public internet (403)
            admin_lock_ok = False
            req_admin = urllib.request.Request(
                f"{target_base}/api/status",
                headers={"User-Agent": ua, "Accept": "application/json"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req_admin, timeout=8.0, context=ctx) as resp:
                    admin_lock_ok = int(resp.status) == 403
            except urllib.error.HTTPError as he:
                admin_lock_ok = int(he.code) == 403
            except Exception:
                admin_lock_ok = False

            # 4) Optional client key verification
            client_key_ok: Optional[bool] = None
            if sample_api_key:
                req_key = urllib.request.Request(
                    f"{target_base}/v1/models",
                    headers={
                        "User-Agent": ua,
                        "Accept": "application/json",
                        "Authorization": f"Bearer {sample_api_key}",
                    },
                    method="GET",
                )
                try:
                    with urllib.request.urlopen(req_key, timeout=8.0, context=ctx) as resp:
                        client_key_ok = int(resp.status) == 200
                except urllib.error.HTTPError:
                    client_key_ok = False
                except Exception:
                    client_key_ok = False

            all_ok = health_ok and auth_lock_ok and admin_lock_ok and (client_key_ok is not False)
            return {
                "ok": all_ok,
                "tested_at": int(time.time()),
                "public_url": target_base,
                "api_base_url": f"{target_base}/v1",
                "latency_ms": latency_ms,
                "browser_connected": bool(health_body.get("browser_connected")),
                "health_ok": health_ok,
                "auth_lock_verified": auth_lock_ok,
                "admin_lock_verified": admin_lock_ok,
                "client_key_verified": client_key_ok,
                "detail": (
                    f"公网 HTTPS 连通正常（延迟 {latency_ms}ms）· 免密访问已拦截 · 管理总台已隐藏保护"
                    if all_ok
                    else "公网已连通，但部分安全策略或客户端密钥状态异常（请检查外部接入总开关是否开启）"
                ),
            }

        result = await asyncio.to_thread(_sync_probe)
        with self._lock:
            self._last_probe = result
        return result

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._refresh_runtime_locked()
            cf_bin = find_cloudflared_binary()
            ts_bin = find_tailscale_binary()
            running = self._pid > 0 and _is_cloudflared_pid_alive(self._pid)
            eff_url = self._active_url or (self.named_public_url if running and self.mode == "named" else "")
            return {
                "cloudflared_installed": bool(cf_bin),
                "tailscale_installed": bool(ts_bin),
                "running": running,
                "pid": self._pid if running else 0,
                "mode": self.mode,
                "target_port": self.target_port,
                "active_url": eff_url,
                "api_base_url": f"{eff_url}/v1" if eff_url else "",
                "auto_sync_public_url": self.auto_sync_public_url,
                "has_named_token": bool(self.named_tunnel_token),
                "named_public_url": self.named_public_url,
                "started_at": self._started_at if running else 0,
                "last_error": self._last_error,
                "last_probe": self._last_probe,
                "recent_logs": self._tail_log_lines(6),
            }
