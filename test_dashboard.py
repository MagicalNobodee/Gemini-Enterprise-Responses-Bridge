"""Check the dashboard script after Python renders the actual HTTP response."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from config import BridgeSettings
from context_builder import ConversationContextBuilder
from schemas import ChatMessage
from server import create_app


def test_served_dashboard_javascript_parses(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node is not None, "Node.js is required to validate the dashboard JavaScript"
    settings = BridgeSettings(auto_export_extension=False, generated_dir=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        response = client.get("/")
    assert response.status_code == 200
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", response.text, re.S | re.I)
    assert scripts, "The dashboard must contain its interactive script"
    for script in scripts:
        result = subprocess.run(
            [node, "--check", "--input-type=commonjs"],
            input=script, capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_dashboard_ui_structure_and_slot_reset_api(tmp_path: Path) -> None:
    settings = BridgeSettings(
        auto_export_extension=False,
        default_model="gemini-4-carbon",
        generated_dir=str(tmp_path),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        html = client.get("/").text
        for required_id in (
            "stepServiceCard",
            "stepExtCard",
            "stepAuthCard",
            "seatsGrid",
            "quickProbeBtn",
            "currencySwitch",
            "dailyBarsStage",
            "taskRatioBar",
            "guideModal",
            "secDiag",
        ):
            assert required_id in html

        status = client.get("/api/status").json()
        assert status["default_model"] == "gemini-4-carbon"
        assert status["api_key_required"] is False

        # Missing slot -> 404
        missing = client.post("/api/slots/reset", json={"slot_key": "ext-none:999"})
        assert missing.status_code == 404

        # Register a mock slot, populate context turns, and reset when idle
        hub = app.state.hub
        ctx_builder = app.state.context_builder
        slot = hub._upsert_single_slot(
            client_id="ext-test",
            tab_id=101,
            tab_url="https://vertexaisearch.cloud.google.com/u/1/home",
            tab_title="Gemini Enterprise",
            tab_ready=True,
            active_model="4-carbon",
        )
        ctx_builder._session_metrics[slot.slot_key] = {
            "turn_count": 6,
            "user_turns": 3,
            "total_context_tokens": 42000,
        }

        # Busy slot must reject reset with 409
        slot.in_flight_request_id = "req-busy"
        busy_res = client.post("/api/slots/reset", json={"slot_key": slot.slot_key})
        assert busy_res.status_code == 409

        # Idle slot resets cleanly and clears context metrics
        slot.in_flight_request_id = None
        ok_res = client.post("/api/slots/reset", json={"slot_key": slot.slot_key})
        assert ok_res.status_code == 200
        assert ok_res.json()["ok"] is True
        assert ctx_builder.get_slot_context_metrics(slot.slot_key) is None


def test_slot_session_title_three_tier_resolution(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    tid_index = "01a1d51f-a5a7-72b1-b8a9-ae451b402ed4"
    tid_sqlite = "01a1d5ae-6d14-7142-9c01-167fc5126869"

    (codex_dir / "session_index.jsonl").write_text(
        json.dumps({"id": tid_index, "thread_name": "分析前端重构需求"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    con = sqlite3.connect(str(codex_dir / "state_5.sqlite"))
    con.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, name TEXT, title TEXT)")
    con.execute(
        "INSERT INTO threads (id, name, title) VALUES (?, ?, ?)",
        (tid_sqlite, "继续写实 Roguelike 项目", "raw prompt"),
    )
    con.commit()
    con.close()

    cb = ConversationContextBuilder(codex_home=codex_dir)

    # Tier 2: Immediate live prompt title extraction before Turn 1 finishes
    cb.build(
        messages=[
            ChatMessage(role="user", content="# AGENTS.md instructions for /tmp\n<INSTRUCTIONS>x</INSTRUCTIONS>"),
            ChatMessage(role="user", content="<environment_context><cwd>/tmp</cwd></environment_context>"),
            ChatMessage(
                role="user",
                content="## Referenced chats:\n[]\n## My request:\n优化 [@记账看板](thread://123) 的柱状图显示",
            ),
        ],
        session_key="ext:202",
    )

    snap = cb.get_context_snapshot(
        [
            {
                "slot_key": "ext:201",
                "tab_id": 201,
                "busy": True,
                "pinned_session_id": tid_index,
                "tab_title": "[System Instructions] You are Codex. You are running...",
                "completed_requests": 5,
            },
            {
                "slot_key": "ext:202",
                "tab_id": 202,
                "busy": True,
                "pinned_session_id": None,
                "tab_title": "[System Instructions] You are Codex...",
                "completed_requests": 0,
            },
            {
                "slot_key": "ext:203",
                "tab_id": 203,
                "busy": False,
                "pinned_session_id": tid_sqlite,
                "tab_title": "Tool stream disconnected - Gemini Enterprise",
                "completed_requests": 12,
            },
            {
                "slot_key": "ext:204",
                "tab_id": 204,
                "busy": False,
                "pinned_session_id": None,
                "tab_title": "微积分极限推导整理 - Gemini Enterprise",
                "completed_requests": 2,
            },
            {
                "slot_key": "ext:205",
                "tab_id": 205,
                "busy": False,
                "pinned_session_id": None,
                "tab_title": "文件完整性检查要点 - Gemini Enterprise",
                "completed_requests": 0,
            },
        ]
    )
    by_key = {s["slot_key"]: s for s in snap["slots"]}
    assert by_key["ext:201"]["session_title"] == "分析前端重构需求"
    assert by_key["ext:201"]["title_source"] == "codex"
    assert by_key["ext:202"]["session_title"] == "优化 @记账看板 的柱状图显示"
    assert by_key["ext:202"]["title_source"] == "prompt"
    assert by_key["ext:203"]["session_title"] == "继续写实 Roguelike 项目"
    assert by_key["ext:203"]["title_source"] == "codex"
    assert by_key["ext:204"]["session_title"] == "微积分极限推导整理"
    assert by_key["ext:204"]["title_source"] == "web"
    # Untouched standby tab ignores stale leftover browser title
    assert by_key["ext:205"]["session_title"] == ""
