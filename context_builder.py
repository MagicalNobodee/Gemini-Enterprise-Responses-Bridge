"""Multi-turn prompt construction, model tracking, and agentic conversation delta tracking."""

from __future__ import annotations

import html
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from schemas import ChatMessage, estimate_tokens, model_requests_new_chat, resolve_target_web_model
from agent_policy import (CARBON_AUTO_COMPACT_TOKENS, CARBON_CONTEXT_WINDOW, CARBON_EFFECTIVE_CONTEXT_PERCENT,
                          CODING_WORKFLOW, COMPACTION_INSTRUCTIONS,
                          has_coding_tools, reading_diagnostics, reading_reminder, deduplicate_tool_text)
from tool_calling import (
    build_response_format_instructions,
    build_tool_delta_reminder,
    build_tool_system_instructions,
    compute_tools_fingerprint,
    format_assistant_history_entry,
    format_tool_result_entry,
    wire_history_entry,
    is_tool_generation_enabled,
)

_CALL_ID_IN_CANON_RE = re.compile(r'"id":\s*"[^"]*",\s*')
_EPHEMERAL_WRAPPER_RE = re.compile(
    r"<(?P<tag>system_reminder|system-reminder|current_datetime|app_user_message_source_json|canvas-context|environment_details|context_info)\b[^>]*>[\s\S]*?</(?P=tag)>",
    re.IGNORECASE,
)
_WHITESPACE_RUN_RE = re.compile(r"\s+")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_METADATA_BLOCK_RE = re.compile(
    r"<(?P<tag>INSTRUCTIONS|environment_context|permissions\s+instructions|collaboration_mode|"
    r"skills_instructions|turn_aborted|image_resize_notice|codex_apps_client_time_context|"
    r"app-context|system_reminder|system-reminder|current_datetime|"
    r"app_user_message_source_json|canvas-context|environment_details|context_info)\b[^>]*>[\s\S]*?</(?P=tag)>",
    re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")

_CODEX_INDEX_CACHE: Dict[str, Any] = {"sig": None, "titles": {}}
_CODEX_SQLITE_CACHE: Dict[str, Tuple[float, str]] = {}


def clean_prompt_to_title(raw_text: str, max_chars: int = 64) -> str:
    """Extract a clean, human-readable topic summary from a raw user message."""
    if not raw_text:
        return ""
    text = html.unescape(raw_text).replace("\xa0", " ")
    text = _METADATA_BLOCK_RE.sub(" ", text).strip()
    if not text:
        return ""

    lowered = text.lower()
    if (
        lowered.startswith("# agents.md instructions")
        or lowered.startswith("[system instructions]")
        or lowered.startswith("[previous session summary]")
        or lowered.startswith("[tool_result]")
    ):
        return ""
    if COMPACTION_INSTRUCTIONS.strip()[:36].lower() in lowered:
        return ""
    if "这是一次连通性体检" in text:
        return "一键模型连通体检"

    if "## My request:" in text:
        text = text.split("## My request:", 1)[1].strip()
    elif "[Current User Request]" in text:
        text = text.rsplit("[Current User Request]", 1)[1].strip()

    text = _MD_LINK_RE.sub(r"\1", text)
    for raw_line in text.splitlines():
        line = re.sub(r"^[#>\-*+\s]+", "", raw_line).strip()
        if not line:
            continue
        if line.startswith("```") or line.startswith("{") or line.startswith("["):
            continue
        line = _WHITESPACE_RUN_RE.sub(" ", line).strip()
        if len(line) > max_chars:
            return line[: max_chars - 1].rstrip() + "…"
        return line
    return ""


def extract_dialogue_title(dialogue: Sequence[Tuple[str, str]]) -> str:
    """Find the first real user topic in normalized dialogue, handling compaction prompts."""
    if not dialogue:
        return ""
    is_compacting = (
        dialogue[-1][0] == "user"
        and COMPACTION_INSTRUCTIONS.strip()[:36].lower() in dialogue[-1][1].lower()
    )
    scan_items = dialogue[:-1] if is_compacting else dialogue
    found = ""
    for role, content in scan_items:
        if role != "user":
            continue
        candidate = clean_prompt_to_title(content)
        if candidate:
            found = candidate
            break
    if is_compacting:
        return f"自动整理记忆 · {found}" if found else "自动整理对话记忆"
    return found


def lookup_codex_thread_title(
    session_id: Optional[str],
    codex_home: Optional[Path] = None,
) -> str:
    """Read-only lookup of a local Codex thread title by UUID (`prompt_cache_key`)."""
    sid = (session_id or "").strip()
    if not sid or not _UUID_RE.match(sid):
        return ""
    root = codex_home or (Path.home() / ".codex")

    # 1) Fast mtime-cached lookup in ~/.codex/session_index.jsonl
    try:
        idx_path = root / "session_index.jsonl"
        if idx_path.is_file():
            st = idx_path.stat()
            sig = (str(idx_path), st.st_mtime_ns, st.st_size)
            if _CODEX_INDEX_CACHE.get("sig") != sig:
                parsed_map: Dict[str, str] = {}
                for raw_line in idx_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = raw_line.strip()
                    if not line or "thread_name" not in line:
                        continue
                    try:
                        obj = json.loads(line)
                        tid = str(obj.get("id") or "").strip()
                        tname = str(obj.get("thread_name") or "").strip()
                        if tid and tname:
                            parsed_map[tid] = tname
                    except Exception:
                        continue
                _CODEX_INDEX_CACHE["sig"] = sig
                _CODEX_INDEX_CACHE["titles"] = parsed_map
            cached_title = (_CODEX_INDEX_CACHE.get("titles") or {}).get(sid, "")
            if cached_title:
                return cached_title
    except Exception:
        pass

    # 2) Read-only fallback in ~/.codex/state_5.sqlite (with 10s TTL per thread ID)
    now = time.monotonic()
    cache_key = f"{root}:{sid}"
    cached_entry = _CODEX_SQLITE_CACHE.get(cache_key)
    if cached_entry is not None and (now - cached_entry[0]) < 10.0:
        return cached_entry[1]

    resolved = ""
    try:
        db_path = root / "state_5.sqlite"
        if db_path.is_file():
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.05)
            try:
                row = con.execute(
                    "SELECT name, title FROM threads WHERE id = ? LIMIT 1",
                    (sid,),
                ).fetchone()
                if row:
                    short_name = str(row[0] or "").strip()
                    raw_first = str(row[1] or "").strip()
                    resolved = short_name or clean_prompt_to_title(raw_first)
            finally:
                con.close()
    except Exception:
        resolved = ""

    _CODEX_SQLITE_CACHE[cache_key] = (now, resolved)
    return resolved


def clean_web_tab_title(raw_title: str, max_chars: int = 56) -> str:
    """Clean a Gemini Enterprise browser tab title and filter out prompt/error noise."""
    if not raw_title:
        return ""
    t = _WHITESPACE_RUN_RE.sub(" ", str(raw_title)).strip()
    t = re.sub(r"\s*[-·|]\s*Gemini Enterprise\s*$", "", t, flags=re.IGNORECASE).strip()
    if not t:
        return ""
    low = t.lower()
    noise_prefixes = (
        "gemini enterprise",
        "vertex ai",
        "google",
        "new chat",
        "[system instructions]",
        "you are codex",
        "# agents.md",
        "<instructions>",
        "<environment_context>",
        "original_stream_",
        "tool_call",
        "[tool_result]",
        "tool stream disconnected",
        "stream disconnected",
    )
    if any(low.startswith(p) for p in noise_prefixes):
        return ""
    if "you are running as a coding agent" in low or "original_stream_" in low:
        return ""
    if len(t) > max_chars:
        return t[: max_chars - 1].rstrip() + "…"
    return t


def resolve_slot_session_title(
    ws: Dict[str, Any],
    prompt_title: str = "",
    turn_count: int = 0,
    codex_home: Optional[Path] = None,
) -> Tuple[str, str]:
    """Resolve (title, source) for a worker slot using Codex -> live prompt -> clean web title."""
    pinned = str(ws.get("pinned_session_id") or "").strip()
    if pinned.startswith("image_"):
        return (prompt_title or "图片生成与编辑任务", "task")
    if pinned.startswith("video_"):
        return (prompt_title or "视频生成任务", "task")
    if pinned.startswith("audio_"):
        return (prompt_title or "语音转写任务", "task")

    codex_title = lookup_codex_thread_title(pinned, codex_home=codex_home)
    if codex_title:
        return (codex_title, "codex")

    if prompt_title:
        return (prompt_title, "prompt")

    has_gateway_activity = (
        bool(ws.get("busy"))
        or int(ws.get("waiting_count") or 0) > 0
        or bool(pinned)
        or turn_count > 0
        or int(ws.get("completed_requests") or 0) > 0
    )
    if has_gateway_activity:
        web_title = clean_web_tab_title(str(ws.get("tab_title") or ""))
        if web_title:
            return (web_title, "web")
    return ("", "")


def _canonicalize_for_match(role: str, text: str) -> str:
    """Strip volatile per-turn client metadata tags and normalize whitespace for prefix comparison."""
    if not text:
        return ""
    cleaned = _EPHEMERAL_WRAPPER_RE.sub("", text)
    if role == "assistant" and "[TOOL_CALL]" in cleaned:
        cleaned = _CALL_ID_IN_CANON_RE.sub("", cleaned)
    return _WHITESPACE_RUN_RE.sub(" ", cleaned).strip()


@dataclass
class PreparedPrompt:
    prompt: str
    reset_chat: bool
    strategy_used: str
    normalized_history: List[Tuple[str, str]]
    target_model: Optional[str] = None
    tools_fingerprint: str = ""
    system_fingerprint: str = ""


class ConversationContextBuilder:
    """Converts stateless OpenAI message arrays (including tool loops) into stateful web prompts."""

    def __init__(
        self,
        default_mode: str = "smart",
        auto_reset_new_chat: bool = True,
        codex_home: Optional[Path] = None,
    ) -> None:
        self.default_mode = default_mode
        self.auto_reset_new_chat = auto_reset_new_chat
        self._codex_home = codex_home
        # Keyed by browser client/tab identifier -> list of (role, canonical_text) already in web chat
        self._session_turns: Dict[str, List[Tuple[str, str]]] = {}
        self._session_models: Dict[str, Optional[str]] = {}
        self._session_tools_fp: Dict[str, str] = {}
        self._session_system_fp: Dict[str, str] = {}
        self._session_metrics: Dict[str, Dict[str, Any]] = {}
        self._session_titles: Dict[str, str] = {}
        self._session_force_reset: set[str] = set()

    def clear_session(self, session_key: str = "default") -> None:
        self._session_turns.pop(session_key, None)
        self._session_models.pop(session_key, None)
        self._session_tools_fp.pop(session_key, None)
        self._session_system_fp.pop(session_key, None)
        self._session_metrics.pop(session_key, None)
        self._session_titles.pop(session_key, None)
        self._session_force_reset.discard(session_key)

    def invalidate_session(self, session_key: str) -> None:
        """A rejected/failed turn cannot be reused, even with automatic resets disabled."""
        self.clear_session(session_key)
        self._session_force_reset.add(session_key)

    def drop_slot(self, session_key: str) -> None:
        self.clear_session(session_key)

    def migrate_slot_key(self, old_key: str, new_key: str) -> None:
        if old_key == new_key:
            return
        for mapping in (self._session_turns, self._session_models, self._session_tools_fp,
                        self._session_system_fp, self._session_metrics, self._session_titles):
            if old_key in mapping:
                mapping[new_key] = mapping.pop(old_key)
        if old_key in self._session_force_reset:
            self._session_force_reset.discard(old_key)
            self._session_force_reset.add(new_key)

    def get_slot_context_metrics(self, session_key: str) -> Optional[Dict[str, Any]]:
        meta = self._session_metrics.get(session_key)
        return dict(meta) if isinstance(meta, dict) else None

    def set_session_title(self, session_key: str, title: str) -> None:
        cleaned = (title or "").strip()
        if session_key and cleaned:
            self._session_titles[session_key] = cleaned

    def _record_dialogue_title(self, session_key: str, dialogue: Sequence[Tuple[str, str]]) -> None:
        extracted = extract_dialogue_title(dialogue)
        if extracted:
            self._session_titles[session_key] = extracted

    def get_context_snapshot(self, worker_slots: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
        eff_limit_default = int(CARBON_CONTEXT_WINDOW * CARBON_EFFECTIVE_CONTEXT_PERCENT / 100)
        slots_out: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        for ws in worker_slots or []:
            if not isinstance(ws, dict):
                continue
            skey = str(ws.get("slot_key") or "")
            if not skey:
                continue
            seen_keys.add(skey)
            meta = self._session_metrics.get(skey) or {}
            t_cnt = int(meta.get("turn_count") or 0)
            sess_title, title_src = resolve_slot_session_title(
                ws,
                prompt_title=self._session_titles.get(skey, "") or str(meta.get("session_title") or ""),
                turn_count=t_cnt,
                codex_home=self._codex_home,
            )
            total_toks = int(meta.get("total_context_tokens") or 0)
            limit_toks = int(meta.get("context_limit_tokens") or CARBON_CONTEXT_WINDOW)
            eff_limit_toks = int(limit_toks * CARBON_EFFECTIVE_CONTEXT_PERCENT / 100)
            compact_toks = int(meta.get("compact_threshold_tokens") or CARBON_AUTO_COMPACT_TOKENS)
            rem_compact = max(0, compact_toks - total_toks)
            rem_context = max(0, limit_toks - total_toks)
            slots_out.append({
                "slot_key": skey,
                "tab_id": ws.get("tab_id"),
                "busy": bool(ws.get("busy")),
                "waiting_count": int(ws.get("waiting_count") or 0),
                "pinned_session_id": ws.get("pinned_session_id"),
                "session_title": sess_title,
                "title_source": title_src,
                "active_model": str(ws.get("active_model") or meta.get("active_model") or ""),
                "turn_count": t_cnt,
                "user_turns": int(meta.get("user_turns") or 0),
                "total_context_tokens": total_toks,
                "context_limit_tokens": limit_toks,
                "effective_limit_tokens": eff_limit_toks,
                "compact_threshold_tokens": compact_toks,
                "remaining_to_compact_tokens": rem_compact,
                "remaining_context_tokens": rem_context,
                "utilization_pct": round(min(100.0, (total_toks / max(limit_toks, 1)) * 100.0), 2),
                "compact_pct": round(min(100.0, (total_toks / max(compact_toks, 1)) * 100.0), 1),
                "last_delta_tokens": int(meta.get("last_delta_tokens") or 0),
                "last_completion_tokens": int(meta.get("last_completion_tokens") or 0),
                "last_strategy": str(meta.get("last_strategy") or ""),
                "updated_at": int(meta.get("updated_at") or ws.get("last_used_at") or 0),
            })
        for skey, meta in self._session_metrics.items():
            if skey in seen_keys:
                continue
            m_copy = dict(meta)
            m_copy.setdefault("session_title", self._session_titles.get(skey, ""))
            m_copy.setdefault("title_source", "prompt" if m_copy.get("session_title") else "")
            t_tok = int(m_copy.get("total_context_tokens") or 0)
            l_tok = int(m_copy.get("context_limit_tokens") or CARBON_CONTEXT_WINDOW)
            c_tok = int(m_copy.get("compact_threshold_tokens") or CARBON_AUTO_COMPACT_TOKENS)
            m_copy.setdefault("effective_limit_tokens", int(l_tok * CARBON_EFFECTIVE_CONTEXT_PERCENT / 100))
            m_copy.setdefault("compact_threshold_tokens", c_tok)
            m_copy.setdefault("remaining_to_compact_tokens", max(0, c_tok - t_tok))
            m_copy.setdefault("remaining_context_tokens", max(0, l_tok - t_tok))
            m_copy["compact_pct"] = round(min(100.0, (t_tok / max(c_tok, 1)) * 100.0), 1)
            slots_out.append(m_copy)
        active_slots = [
            s for s in slots_out
            if bool(s.get("busy")) or int(s.get("turn_count") or 0) > 0 or bool(s.get("session_title"))
        ]
        active_slots.sort(key=lambda s: (1 if s.get("busy") else 0, int(s.get("updated_at") or 0)), reverse=True)
        primary = active_slots[0] if active_slots else ({
            "slot_key": "",
            "tab_id": None,
            "busy": False,
            "session_title": "",
            "title_source": "",
            "active_model": "",
            "turn_count": 0,
            "user_turns": 0,
            "total_context_tokens": 0,
            "context_limit_tokens": CARBON_CONTEXT_WINDOW,
            "effective_limit_tokens": eff_limit_default,
            "compact_threshold_tokens": CARBON_AUTO_COMPACT_TOKENS,
            "remaining_to_compact_tokens": CARBON_AUTO_COMPACT_TOKENS,
            "remaining_context_tokens": CARBON_CONTEXT_WINDOW,
            "utilization_pct": 0.0,
            "compact_pct": 0.0,
            "last_delta_tokens": 0,
            "last_completion_tokens": 0,
            "last_strategy": "",
            "updated_at": 0,
        })
        return {
            "primary": primary,
            "slots": slots_out,
            "active_session_count": len(active_slots),
        }

    def get_session_model(self, session_key: str = "default") -> Optional[str]:
        return self._session_models.get(session_key)

    def has_active_conversation(self, session_key: str) -> bool:
        return bool(self._session_turns.get(session_key))

    def has_active_tool_session(self, session_key: str) -> bool:
        """Return True if `session_key` holds an active multi-turn tool-enabled conversation."""
        return bool(self._session_tools_fp.get(session_key)) and len(
            self._session_turns.get(session_key) or []
        ) >= 2

    @staticmethod
    def _system_prompts_compatible(
        prev_sys_fp: Optional[str],
        cur_sys_text: str,
        has_tracked_dialogue: bool = False,
    ) -> Tuple[bool, str]:
        """Return (compatible, appended_system_delta) tolerating volatile tags or appended skill blocks."""
        if prev_sys_fp is None or prev_sys_fp == cur_sys_text:
            return (True, "")
        c_prev = _canonicalize_for_match("system", prev_sys_fp)
        c_cur = _canonicalize_for_match("system", cur_sys_text)
        if c_prev == c_cur:
            return (True, "")
        if has_tracked_dialogue:
            if cur_sys_text.startswith(prev_sys_fp):
                return (True, cur_sys_text[len(prev_sys_fp) :].strip())
            # If the system prompt shares the primary prefix or only mutated dynamic sections, keep session alive
            common_prefix_len = 0
            for ch1, ch2 in zip(c_prev, c_cur):
                if ch1 != ch2:
                    break
                common_prefix_len += 1
            min_len = min(len(c_prev), len(c_cur))
            if min_len > 0 and common_prefix_len >= int(min_len * 0.65):
                prev_paras = {p.strip() for p in prev_sys_fp.split("\n\n") if p.strip()}
                new_paras = [
                    p.strip()
                    for p in cur_sys_text.split("\n\n")
                    if p.strip() and p.strip() not in prev_paras
                ]
                delta_sys = "\n\n".join(new_paras).strip()
                return (True, f"[Updated System Instructions]\n{delta_sys}" if delta_sys else "")
        return (False, "")

    @staticmethod
    def _normalize_messages(messages: Sequence[ChatMessage]) -> Tuple[str, List[Tuple[str, str]]]:
        system_parts: List[str] = []
        dialogue: List[Tuple[str, str]] = []
        call_id_to_name: Dict[str, str] = {}
        seen_tool_outputs: Dict[str, str] = {}

        for msg in messages:
            role = (msg.role or "user").strip().lower()
            text = msg.text_content().strip()

            if role in {"system", "developer"}:
                if text:
                    system_parts.append(text)
                continue

            if role == "assistant":
                tcs = msg.normalized_tool_calls()
                for tc in tcs:
                    tc_id = str(tc.get("id") or "")
                    fn_name = str((tc.get("function") or {}).get("name") or "")
                    if tc_id and fn_name:
                        call_id_to_name[tc_id] = fn_name
                if tcs:
                    canon_asst = format_assistant_history_entry(text, tcs)
                    dialogue.append(("assistant", canon_asst))
                elif text:
                    dialogue.append(("assistant", text))
                continue

            if role in {"tool", "function"}:
                resolved_name = msg.name or (
                    call_id_to_name.get(msg.tool_call_id) if msg.tool_call_id else None
                )
                if isinstance(msg.content, str):
                    text = deduplicate_tool_text(text, msg.tool_call_id or "", seen_tool_outputs)
                formatted_tool = format_tool_result_entry(
                    text,
                    tool_call_id=msg.tool_call_id,
                    name=resolved_name,
                )
                dialogue.append(("tool", formatted_tool))
                continue

            if text:
                dialogue.append(("user", text))

        return ("\n\n".join(system_parts).strip(), dialogue)

    def find_matching_slots(
        self,
        candidate_slot_keys: Sequence[str],
        messages: Sequence[ChatMessage],
        model: str = "gemini-enterprise-web",
    ) -> List[str]:
        """Find worker slot keys whose active browser conversation matches `messages`'s prefix."""
        if not candidate_slot_keys or model_requests_new_chat(model):
            return []

        user_system_text, dialogue = self._normalize_messages(messages)
        if len(dialogue) <= 1:
            return []
        if dialogue[-1][0] == "user" and dialogue[-1][1].startswith("[NEW_CHAT]"):
            return []

        matched: List[Tuple[int, str]] = []
        for slot_key in candidate_slot_keys:
            tracked = self._session_turns.get(slot_key)
            if not tracked or len(tracked) >= len(dialogue):
                continue
            prev_sys_fp = self._session_system_fp.get(slot_key)
            sys_ok, _ = self._system_prompts_compatible(
                prev_sys_fp, user_system_text, has_tracked_dialogue=len(tracked) >= 2
            )
            if not sys_ok:
                continue
            if self._history_matches(tracked, dialogue[: len(tracked)]):
                matched.append((len(tracked), slot_key))

        matched.sort(key=lambda item: item[0], reverse=True)
        return [slot_key for _, slot_key in matched]

    def record_completed_turn(
        self,
        session_key: str,
        sent_history: List[Tuple[str, str]],
        assistant_reply: Optional[str] = "",
        assistant_tool_calls: Optional[Sequence[Dict[str, Any]]] = None,
        active_model: Optional[str] = None,
        tools_fingerprint: Optional[str] = None,
        system_fingerprint: Optional[str] = None,
        logical_prompt_tokens: Optional[int] = None,
        web_prompt_tokens: Optional[int] = None,
        last_strategy: Optional[str] = None,
    ) -> None:
        updated = list(sent_history)
        if assistant_tool_calls:
            canon = format_assistant_history_entry(assistant_reply or "", assistant_tool_calls)
        else:
            canon = (assistant_reply or "").strip()
        updated.append(("assistant", canon))
        self._session_turns[session_key] = updated
        if active_model is not None:
            self._session_models[session_key] = active_model
        if tools_fingerprint is not None:
            self._session_tools_fp[session_key] = tools_fingerprint
        if system_fingerprint is not None:
            self._session_system_fp[session_key] = system_fingerprint

        comp_tokens = estimate_tokens(canon)
        if logical_prompt_tokens is not None:
            total_ctx = max(0, int(logical_prompt_tokens)) + comp_tokens
        else:
            sys_t = estimate_tokens(self._session_system_fp.get(session_key) or "")
            total_ctx = sys_t + sum(estimate_tokens(t) for _, t in updated)
        eff_model = active_model or self._session_models.get(session_key) or ""
        rem_compact = max(0, CARBON_AUTO_COMPACT_TOKENS - total_ctx)
        rem_context = max(0, CARBON_CONTEXT_WINDOW - total_ctx)
        self._session_metrics[session_key] = {
            "slot_key": session_key,
            "tab_id": None,
            "busy": False,
            "session_title": self._session_titles.get(session_key, ""),
            "active_model": eff_model,
            "turn_count": len(updated),
            "user_turns": sum(1 for r, _ in updated if r == "user"),
            "total_context_tokens": total_ctx,
            "context_limit_tokens": CARBON_CONTEXT_WINDOW,
            "effective_limit_tokens": int(CARBON_CONTEXT_WINDOW * CARBON_EFFECTIVE_CONTEXT_PERCENT / 100),
            "compact_threshold_tokens": CARBON_AUTO_COMPACT_TOKENS,
            "remaining_to_compact_tokens": rem_compact,
            "remaining_context_tokens": rem_context,
            "utilization_pct": round(min(100.0, (total_ctx / max(CARBON_CONTEXT_WINDOW, 1)) * 100.0), 2),
            "compact_pct": round(min(100.0, (total_ctx / max(CARBON_AUTO_COMPACT_TOKENS, 1)) * 100.0), 1),
            "last_delta_tokens": max(0, int(web_prompt_tokens or 0)),
            "last_completion_tokens": comp_tokens,
            "last_strategy": last_strategy or "smart_single_turn",
            "updated_at": int(time.time()),
        }

    def build(
        self,
        messages: Sequence[ChatMessage],
        model: str = "gemini-enterprise-web",
        session_key: str = "default",
        mode_override: str | None = None,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        parallel_tool_calls: Optional[bool] = True,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> PreparedPrompt:
        mode = (mode_override or self.default_mode or "smart").lower()
        explicit_new_chat = model_requests_new_chat(model) or session_key in self._session_force_reset
        target_model = resolve_target_web_model(model)

        norm_tools = list(tools or [])
        tools_fp = (
            compute_tools_fingerprint(norm_tools)
            if is_tool_generation_enabled(norm_tools, tool_choice)
            else ""
        )

        user_system_text, dialogue = self._normalize_messages(messages)

        tool_sys_text = build_tool_system_instructions(
            norm_tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
        )
        if has_coding_tools(norm_tools) and tool_sys_text and CODING_WORKFLOW.strip() not in user_system_text:
            tool_sys_text += "\n\n" + CODING_WORKFLOW
        fmt_sys_text = build_response_format_instructions(response_format)

        combined_sys_sections = [s for s in (user_system_text, tool_sys_text, fmt_sys_text) if s]
        combined_system_text = "\n\n".join(combined_sys_sections).strip()

        if not dialogue:
            fallback_prompt = combined_system_text or "Hello"
            reset_only_sys = explicit_new_chat or self.auto_reset_new_chat
            if reset_only_sys:
                self.clear_session(session_key)
            return PreparedPrompt(
                prompt=fallback_prompt,
                reset_chat=reset_only_sys,
                strategy_used="system_only",
                normalized_history=[("user", fallback_prompt)],
                target_model=target_model,
                tools_fingerprint=tools_fp,
                system_fingerprint=user_system_text,
            )

        # Check inline [NEW_CHAT] directive on trailing user turn
        if dialogue[-1][0] == "user" and dialogue[-1][1].startswith("[NEW_CHAT]"):
            explicit_new_chat = True
            stripped_user = dialogue[-1][1][len("[NEW_CHAT]") :].lstrip()
            dialogue[-1] = ("user", stripped_user)

        if explicit_new_chat:
            self.clear_session(session_key)

        has_trailing_tool_results = any(
            r == "tool" for r, _ in self._trailing_non_assistant_slice(dialogue)
        )
        delta_reminder = build_tool_delta_reminder(
            norm_tools,
            tool_choice=tool_choice,
            has_tool_results=has_trailing_tool_results,
        )

        if has_coding_tools(norm_tools):
            read_hint = reading_reminder(reading_diagnostics(messages))
            if read_hint:
                delta_reminder = "\n\n".join(filter(None, [delta_reminder, read_hint]))

        # Track target_model transition on this session_key (UI switches model in-place cleanly)
        if target_model is not None:
            self._session_models[session_key] = target_model

        if mode == "last_message":
            tail_prompt = self._format_delta_entries(
                self._trailing_non_assistant_slice(dialogue) or [dialogue[-1]],
                extra_instructions=[fmt_sys_text, delta_reminder] if len(dialogue) > 1 else [],
            )
            reset_last = explicit_new_chat or (self.auto_reset_new_chat and len(dialogue) == 1)
            if reset_last:
                self.clear_session(session_key)
            self._record_dialogue_title(session_key, dialogue)
            prompt = self._with_system_if_first_turn(
                last_text=tail_prompt,
                system_text=combined_system_text,
                is_first_turn=len(dialogue) == 1,
            )
            return PreparedPrompt(
                prompt=prompt,
                reset_chat=reset_last,
                strategy_used="last_message",
                normalized_history=dialogue,
                target_model=target_model,
                tools_fingerprint=tools_fp,
                system_fingerprint=user_system_text,
            )

        if mode == "transcript":
            reset_trans = explicit_new_chat or self.auto_reset_new_chat
            if reset_trans:
                self.clear_session(session_key)
            self._record_dialogue_title(session_key, dialogue)
            prompt = self._format_full_transcript(
                system_text=combined_system_text,
                dialogue=dialogue,
                trailing_reminder=delta_reminder,
            )
            return PreparedPrompt(
                prompt=prompt,
                reset_chat=reset_trans,
                strategy_used="transcript",
                normalized_history=dialogue,
                target_model=target_model,
                tools_fingerprint=tools_fp,
                system_fingerprint=user_system_text,
            )

        # Smart mode:
        # 1) Single-turn user prompt -> brand-new local conversation!
        #    When `auto_reset_new_chat` is True (default), ALWAYS reset_chat=True (even on the first
        #    request after server startup, in case the browser tab already has an old `/r/session/...` open;
        #    page-driver.js fast-paths in 0ms if the tab is already on a blank new chat).
        if len(dialogue) == 1 and dialogue[0][0] == "user":
            reset_chat = explicit_new_chat or self.auto_reset_new_chat
            if reset_chat:
                self.clear_session(session_key)
                if target_model is not None:
                    self._session_models[session_key] = target_model
            self._record_dialogue_title(session_key, dialogue)
            prompt = self._with_system_if_first_turn(
                last_text=dialogue[0][1],
                system_text=combined_system_text,
                is_first_turn=True,
            )
            return PreparedPrompt(
                prompt=prompt,
                reset_chat=reset_chat,
                strategy_used="smart_single_turn",
                normalized_history=dialogue,
                target_model=target_model,
                tools_fingerprint=tools_fp,
                system_fingerprint=user_system_text,
            )

        # 2) Multi-turn continuation of the SAME local conversation (including tool_result loops!)
        tracked = self._session_turns.get(session_key)
        prev_sys_fp = self._session_system_fp.get(session_key)
        system_matches, sys_delta_block = self._system_prompts_compatible(
            prev_sys_fp, user_system_text, has_tracked_dialogue=bool(tracked and len(tracked) >= 2)
        )
        if (
            not explicit_new_chat
            and tracked
            and system_matches
            and len(tracked) < len(dialogue)
            and self._history_matches(tracked, dialogue[: len(tracked)])
        ):
            delta_entries = dialogue[len(tracked) :]
            prev_fp = self._session_tools_fp.get(session_key, "")
            extra_blocks: List[str] = []
            if sys_delta_block:
                extra_blocks.append(sys_delta_block)
            if tools_fp and tools_fp != prev_fp and tool_sys_text:
                extra_blocks.append(tool_sys_text)
            if fmt_sys_text:
                extra_blocks.append(fmt_sys_text)

            delta_has_tools = any(r == "tool" for r, _ in delta_entries)
            inc_reminder = build_tool_delta_reminder(
                norm_tools,
                tool_choice=tool_choice,
                has_tool_results=delta_has_tools,
            )
            if has_coding_tools(norm_tools):
                read_hint = reading_reminder(reading_diagnostics(messages))
                inc_reminder = "\n\n".join(filter(None, [inc_reminder, read_hint]))
            if inc_reminder:
                extra_blocks.append(inc_reminder)
            self._record_dialogue_title(session_key, dialogue)
            prompt = self._format_delta_entries(delta_entries, extra_instructions=extra_blocks)
            return PreparedPrompt(
                prompt=prompt,
                reset_chat=False,
                strategy_used="smart_incremental_delta",
                normalized_history=dialogue,
                target_model=target_model,
                tools_fingerprint=tools_fp,
                system_fingerprint=user_system_text,
            )

        # 3) Switched to a DIFFERENT multi-turn local conversation not matching current browser tab:
        #    Start a clean web session (`reset_chat=True` when auto_reset_new_chat=True) and pack its history.
        reset_packed = explicit_new_chat or self.auto_reset_new_chat
        if reset_packed:
            self.clear_session(session_key)
            if target_model is not None:
                self._session_models[session_key] = target_model
        self._record_dialogue_title(session_key, dialogue)
        prompt = self._format_full_transcript(
            system_text=combined_system_text,
            dialogue=dialogue,
            trailing_reminder=delta_reminder,
        )
        return PreparedPrompt(
            prompt=prompt,
            reset_chat=reset_packed,
            strategy_used="smart_packed_context",
            normalized_history=dialogue,
            target_model=target_model,
            tools_fingerprint=tools_fp,
            system_fingerprint=user_system_text,
        )

    @staticmethod
    def _trailing_non_assistant_slice(dialogue: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
        idx = len(dialogue)
        while idx > 0 and dialogue[idx - 1][0] != "assistant":
            idx -= 1
        return list(dialogue[idx:])

    @staticmethod
    def _format_delta_entries(
        delta_entries: Sequence[Tuple[str, str]],
        extra_instructions: Optional[Sequence[str]] = None,
    ) -> str:
        extras = [e.strip() for e in (extra_instructions or []) if e and e.strip()]
        if len(delta_entries) == 1 and delta_entries[0][0] == "user" and not extras:
            return delta_entries[0][1]

        blocks: List[str] = []
        for role, content in delta_entries:
            content = wire_history_entry(role, content)
            if role == "tool":
                blocks.append(content)
            elif role == "assistant":
                blocks.append(f"Assistant: {content}")
            else:
                blocks.append(content if len(delta_entries) == 1 else f"User: {content}")

        if delta_entries and delta_entries[-1][0] == "assistant":
            blocks.append("Please continue based on the conversation above.")

        blocks.extend(extras)
        return "\n\n".join(b for b in blocks if b)

    @classmethod
    def _history_matches(
        cls,
        tracked: Sequence[Tuple[str, str]],
        incoming_prefix: Sequence[Tuple[str, str]],
    ) -> bool:
        if len(tracked) != len(incoming_prefix):
            return False
        for (r1, t1), (r2, t2) in zip(tracked, incoming_prefix):
            if r1 != r2:
                return False
            s1 = t1.strip()
            s2 = t2.strip()
            if s1 == s2:
                continue
            if _canonicalize_for_match(r1, s1) == _canonicalize_for_match(r2, s2):
                continue
            return False
        return True

    @staticmethod
    def _with_system_if_first_turn(last_text: str, system_text: str, is_first_turn: bool) -> str:
        if system_text and is_first_turn:
            return f"[System Instructions]\n{system_text}\n\n[User Request]\n{last_text}"
        return last_text

    @classmethod
    def _format_full_transcript(
        cls,
        system_text: str,
        dialogue: Sequence[Tuple[str, str]],
        trailing_reminder: str = "",
    ) -> str:
        sections: List[str] = []
        if system_text:
            sections.append(f"[System Instructions]\n{system_text}")

        tail = cls._trailing_non_assistant_slice(dialogue)
        split_idx = len(dialogue) - len(tail) if tail else max(0, len(dialogue) - 1)
        prior = dialogue[:split_idx]
        current_entries = dialogue[split_idx:]

        if prior:
            lines: List[str] = ["[Conversation History]"]
            for role, content in prior:
                content = wire_history_entry(role, content)
                if role == "user":
                    lines.append(f"User: {content}")
                elif role == "assistant":
                    lines.append(f"Assistant: {content}")
                else:
                    lines.append(content)
            sections.append("\n".join(lines))

        current_body = cls._format_delta_entries(
            current_entries,
            extra_instructions=[trailing_reminder] if trailing_reminder else None,
        )
        heading = (
            "[Tool Execution Results]"
            if current_entries and all(r == "tool" for r, _ in current_entries)
            else "[Current User Request]"
        )
        sections.append(f"{heading}\n{current_body}")
        return "\n\n".join(sections)
