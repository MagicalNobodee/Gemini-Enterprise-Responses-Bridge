"""End-to-end regression tests for persistent slot affinity, true LRU SQLite archiving, and /r/session/<id> re-entry."""

from __future__ import annotations

from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from config import BridgeSettings
from server import create_app


def _make_settings(tmp_path: Path, **overrides) -> BridgeSettings:
    defaults = dict(
        auto_export_extension=False,
        auto_spawn_tabs=False,
        auto_reset_new_chat=True,
        max_parallel_tabs=2,
        generated_dir=str(tmp_path / "generated"),
        response_store_dir=str(tmp_path / "store"),
        session_archive_path=str(tmp_path / "session_archive.sqlite3"),
    )
    defaults.update(overrides)
    return BridgeSettings(**defaults)


def _recv_next_meaningful(ws) -> dict:
    msg = ws.receive_json()
    chunks = {}
    while msg.get("type") in {"welcome", "ack", "pong", "cancel_request", "execute_prompt_chunk"}:
        if msg.get("type") == "execute_prompt_chunk":
            chunks[msg["chunk_index"]] = msg["data"]
        msg = ws.receive_json()
    if msg.get("type") == "execute_prompt" and msg.get("chunked"):
        msg["prompt"] = "".join(chunks[i] for i in range(msg["total_chunks"]))
    return msg


def test_ws_disconnect_reconnect_preserves_slot_and_inherits_prompt_cache_key(tmp_path: Path):
    app = create_app(_make_settings(tmp_path))
    dispatched = []
    sess_url = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-ws-101"

    with TestClient(app) as client:
        # Phase 1: Turn 1 on WS connection #1
        with client.websocket_connect("/ws/browser?client_id=ext-mv3") as ws1:
            ws1.receive_json()  # welcome
            ws1.send_json(
                {
                    "type": "tab_status",
                    "capabilities": ["multi_tab", "reset_tab", "open_session"],
                    "tabs": [
                        {
                            "tab_id": 101,
                            "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home",
                            "ready": True,
                        }
                    ],
                    "ready": True,
                }
            )
            ws1.receive_json()  # ack

            def worker1():
                cmd = _recv_next_meaningful(ws1)
                dispatched.append(cmd)
                ws1.send_json(
                    {
                        "type": "request_complete",
                        "request_id": cmd["request_id"],
                        "tab_id": cmd["tab_id"],
                        "tab_url": sess_url,
                        "tab_title": "Task 101",
                        "reply": "turn1-ok",
                    }
                )

            t1 = threading.Thread(target=worker1, daemon=True)
            t1.start()
            resp1 = client.post(
                "/v1/responses",
                json={
                    "model": "gemini-4-carbon",
                    "prompt_cache_key": "codex-session-mv3",
                    "input": "FIRST_UNIQUE_SEED_101",
                },
            ).json()
            t1.join(timeout=3)
            assert resp1["status"] == "completed"
            assert resp1.get("prompt_cache_key") == "codex-session-mv3"

        # WS1 is now closed (simulating Chrome MV3 service worker 30s idle sleep).
        # Reconnect WS2 with same client_id and tab_id=101.
        with client.websocket_connect("/ws/browser?client_id=ext-mv3") as ws2:
            ws2.receive_json()
            ws2.send_json(
                {
                    "type": "tab_status",
                    "capabilities": ["multi_tab", "reset_tab", "open_session"],
                    "tabs": [{"tab_id": 101, "tab_url": sess_url, "ready": True}],
                    "ready": True,
                }
            )
            ws2.receive_json()

            def worker2():
                for idx in (2, 3):
                    cmd = _recv_next_meaningful(ws2)
                    dispatched.append(cmd)
                    ws2.send_json(
                        {
                            "type": "request_complete",
                            "request_id": cmd["request_id"],
                            "tab_id": cmd["tab_id"],
                            "tab_url": sess_url,
                            "reply": f"turn{idx}-ok",
                        }
                    )

            t2 = threading.Thread(target=worker2, daemon=True)
            t2.start()
            # Turn 2 omits prompt_cache_key, relying on previous_response_id inheritance!
            resp2 = client.post(
                "/v1/responses",
                json={
                    "model": "gemini-4-carbon",
                    "previous_response_id": resp1["id"],
                    "input": "SECOND_DELTA_101",
                },
            ).json()
            assert resp2["status"] == "completed"
            assert resp2.get("prompt_cache_key") == "codex-session-mv3"

            # Turn 3 also omits prompt_cache_key across a 2-hop chain!
            resp3 = client.post(
                "/v1/responses",
                json={
                    "model": "gemini-4-carbon",
                    "previous_response_id": resp2["id"],
                    "input": "THIRD_DELTA_101",
                },
            ).json()
            t2.join(timeout=3)
            assert resp3["status"] == "completed"

    assert len(dispatched) == 3
    assert dispatched[1]["tab_id"] == 101 and dispatched[1]["reset_chat"] is False
    assert "FIRST_UNIQUE_SEED_101" not in dispatched[1]["prompt"]
    assert "SECOND_DELTA_101" in dispatched[1]["prompt"]
    assert dispatched[2]["tab_id"] == 101 and dispatched[2]["reset_chat"] is False
    assert "SECOND_DELTA_101" not in dispatched[2]["prompt"]
    assert "THIRD_DELTA_101" in dispatched[2]["prompt"]


def test_long_idle_session_never_evicted_and_auto_spawns_before_eviction(tmp_path: Path):
    app = create_app(_make_settings(tmp_path, max_parallel_tabs=3, auto_spawn_tabs=True))
    events = []
    url_a = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-idle-A"
    url_b = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-idle-B"

    with TestClient(app) as client, client.websocket_connect("/ws/browser?client_id=ext-spawn") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "tab_status",
                "capabilities": ["multi_tab", "reset_tab", "spawn_tab", "open_session"],
                "max_parallel_tabs": 3,
                "tabs": [
                    {
                        "tab_id": 101,
                        "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home",
                        "ready": True,
                    }
                ],
                "ready": True,
            }
        )
        ws.receive_json()

        # 1) Session A runs on tab 101
        def step1():
            cmd = _recv_next_meaningful(ws)
            events.append(cmd)
            ws.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 101,
                    "tab_url": url_a,
                    "reply": "A1-done",
                }
            )

        th = threading.Thread(target=step1, daemon=True)
        th.start()
        resp_a1 = client.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "sess-A", "input": "SEED_TASK_A"},
        ).json()
        th.join(timeout=3)
        assert resp_a1["status"] == "completed"

        # Simulate 4 hours of user inactivity on Session A (well past the old 5-minute TTL)
        app.state.hub._slots["ext-spawn:101"].last_used_at = time.time() - 14400.0

        # 2) Brand-new Session B arrives -> must spawn tab 102 rather than evicting idle tab 101!
        def step2():
            msg = _recv_next_meaningful(ws)
            events.append(msg)
            assert msg["type"] == "spawn_tab"
            ws.send_json(
                {
                    "type": "spawn_tab_result",
                    "spawn_id": msg["spawn_id"],
                    "ok": True,
                    "tab": {
                        "tab_id": 102,
                        "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home",
                        "ready": True,
                    },
                }
            )
            cmd = _recv_next_meaningful(ws)
            events.append(cmd)
            ws.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 102,
                    "tab_url": url_b,
                    "reply": "B1-done",
                }
            )

        th = threading.Thread(target=step2, daemon=True)
        th.start()
        resp_b1 = client.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "sess-B", "input": "SEED_TASK_B"},
        ).json()
        th.join(timeout=3)
        assert resp_b1["status"] == "completed"

        # 3) Session A resumes after 4 hours -> hits original tab 101 incrementally!
        def step3():
            cmd = _recv_next_meaningful(ws)
            events.append(cmd)
            ws.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 101,
                    "tab_url": url_a,
                    "reply": "A2-done",
                }
            )

        th = threading.Thread(target=step3, daemon=True)
        th.start()
        resp_a2 = client.post(
            "/v1/responses",
            json={
                "model": "gemini-4-carbon",
                "previous_response_id": resp_a1["id"],
                "input": "FOLLOWUP_TASK_A",
            },
        ).json()
        th.join(timeout=3)
        assert resp_a2["status"] == "completed"

    prompt_cmds = [e for e in events if e.get("type") == "execute_prompt"]
    assert [c["tab_id"] for c in prompt_cmds] == [101, 102, 101]
    assert prompt_cmds[2]["reset_chat"] is False
    assert "SEED_TASK_A" not in prompt_cmds[2]["prompt"]


def test_full_pool_lru_eviction_and_open_session_reentry_plus_redirect_fallback(tmp_path: Path):
    app = create_app(_make_settings(tmp_path, max_parallel_tabs=2, auto_spawn_tabs=False))
    url_a = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-lru-A"
    url_b = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-lru-B"
    url_c = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-lru-C"

    with TestClient(app) as client, client.websocket_connect("/ws/browser?client_id=ext-lru") as ws:
        ws.receive_json()
        ws.send_json(
            {
                "type": "tab_status",
                "capabilities": ["multi_tab", "reset_tab", "open_session"],
                "max_parallel_tabs": 2,
                "tabs": [
                    {"tab_id": 201, "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home", "ready": True},
                    {"tab_id": 202, "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home", "ready": True},
                ],
                "ready": True,
            }
        )
        ws.receive_json()

        def run_simple_turn(target_url: str, reply_text: str) -> dict:
            captured = {}

            def w():
                cmd = _recv_next_meaningful(ws)
                captured["cmd"] = cmd
                ws.send_json(
                    {
                        "type": "request_complete",
                        "request_id": cmd["request_id"],
                        "tab_id": cmd["tab_id"],
                        "tab_url": target_url,
                        "reply": reply_text,
                    }
                )

            t = threading.Thread(target=w, daemon=True)
            t.start()
            captured["thread"] = t
            return captured

        # 1) Populate tab 201 with Session A, tab 202 with Session B
        cap_a = run_simple_turn(url_a, "reply-A1")
        resp_a1 = client.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "lru-A", "input": "ALPHA_INITIAL_HISTORY"},
        ).json()
        cap_a["thread"].join(timeout=3)
        assert cap_a["cmd"]["tab_id"] == 201

        cap_b = run_simple_turn(url_b, "reply-B1")
        resp_b1 = client.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "lru-B", "input": "BETA_INITIAL_HISTORY"},
        ).json()
        cap_b["thread"].join(timeout=3)
        assert cap_b["cmd"]["tab_id"] == 202

        # Make tab 201 strictly older than tab 202
        app.state.hub._slots["ext-lru:201"].last_used_at = 1000.0
        app.state.hub._slots["ext-lru:202"].last_used_at = 2000.0

        # 2) New Session C arrives when pool (2/2) is full -> must evict oldest (tab 201, Session A)!
        cap_c = run_simple_turn(url_c, "reply-C1")
        resp_c1 = client.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "lru-C", "input": "GAMMA_INITIAL_HISTORY"},
        ).json()
        cap_c["thread"].join(timeout=3)
        assert resp_c1["status"] == "completed"
        assert cap_c["cmd"]["tab_id"] == 201
        assert cap_c["cmd"]["reset_chat"] is True

        # Verify Session A is persisted in SQLite archive
        archived_a = app.state.context_builder._archive.get_by_explicit_session_id("lru-A")
        assert archived_a is not None and archived_a.vertex_session_id == "vsid-lru-A"

        # Now tab 202 (last_used_at=2000.0, Session B) is older than tab 201 (Session C, just used).
        # 3) Old Session A returns -> must evict tab 202 (Session B), call open_session(url_a), and send delta with reset_chat=False!
        reentry_events = []

        def w_reenter_a():
            nav = _recv_next_meaningful(ws)
            reentry_events.append(nav)
            assert nav["type"] == "open_session"
            assert nav["tab_id"] == 202
            assert nav["session_url"] == url_a
            ws.send_json(
                {
                    "type": "open_session_result",
                    "open_id": nav["open_id"],
                    "ok": True,
                    "tab_id": 202,
                    "tab_url": url_a,
                    "tab_title": "Resumed A",
                }
            )
            cmd = _recv_next_meaningful(ws)
            reentry_events.append(cmd)
            ws.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 202,
                    "tab_url": url_a,
                    "reply": "reply-A2",
                }
            )

        t_a2 = threading.Thread(target=w_reenter_a, daemon=True)
        t_a2.start()
        resp_a2 = client.post(
            "/v1/responses",
            json={
                "model": "gemini-4-carbon",
                "previous_response_id": resp_a1["id"],
                "input": "ALPHA_STEP_TWO",
            },
        ).json()
        t_a2.join(timeout=3)
        assert resp_a2["status"] == "completed"
        exec_a2 = reentry_events[1]
        assert exec_a2["tab_id"] == 202
        assert exec_a2["reset_chat"] is False
        assert "ALPHA_INITIAL_HISTORY" not in exec_a2["prompt"]
        assert "ALPHA_STEP_TWO" in exec_a2["prompt"]

        # 4) Old Session B returns, but Gemini redirects /r/session/vsid-lru-B back to /home (open_session fails)!
        # Must clean up dead archive entry and gracefully degrade to reset_chat=True with full history.
        fallback_events = []

        def w_fallback_b():
            nav = _recv_next_meaningful(ws)
            fallback_events.append(nav)
            assert nav["type"] == "open_session"
            assert nav["session_url"] == url_b
            ws.send_json(
                {
                    "type": "open_session_result",
                    "open_id": nav["open_id"],
                    "ok": False,
                    "tab_id": nav["tab_id"],
                    "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home",
                    "error": "历史会话已被重定向回空白首页",
                }
            )
            cmd = _recv_next_meaningful(ws)
            fallback_events.append(cmd)
            ws.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": cmd["tab_id"],
                    "tab_url": "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-lru-B-new",
                    "reply": "reply-B2-rebuilt",
                }
            )

        t_b2 = threading.Thread(target=w_fallback_b, daemon=True)
        t_b2.start()
        resp_b2 = client.post(
            "/v1/responses",
            json={
                "model": "gemini-4-carbon",
                "previous_response_id": resp_b1["id"],
                "input": "BETA_STEP_TWO",
            },
        ).json()
        t_b2.join(timeout=3)
        assert resp_b2["status"] == "completed"
        exec_b2 = fallback_events[1]
        assert exec_b2["reset_chat"] is True
        assert "BETA_INITIAL_HISTORY" in exec_b2["prompt"]
        assert "BETA_STEP_TWO" in exec_b2["prompt"]


def test_server_restart_hydrates_live_tabs_from_sqlite_archive(tmp_path: Path):
    url_e = "https://vertexaisearch.cloud.google.com/u/0/app/cid1/r/session/vsid-restart-301"

    # Process Instance #1
    app1 = create_app(_make_settings(tmp_path))
    with TestClient(app1) as client1, client1.websocket_connect("/ws/browser?client_id=ext-r") as ws1:
        ws1.receive_json()
        ws1.send_json(
            {
                "type": "tab_status",
                "capabilities": ["multi_tab", "reset_tab", "open_session"],
                "tabs": [{"tab_id": 301, "tab_url": "https://vertexaisearch.cloud.google.com/u/0/home", "ready": True}],
                "ready": True,
            }
        )
        ws1.receive_json()

        def w1():
            cmd = _recv_next_meaningful(ws1)
            ws1.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 301,
                    "tab_url": url_e,
                    "reply": "E1-done",
                }
            )

        t1 = threading.Thread(target=w1, daemon=True)
        t1.start()
        resp_e1 = client1.post(
            "/v1/responses",
            json={"model": "gemini-4-carbon", "prompt_cache_key": "restart-E", "input": "RESTART_SEED_HISTORY"},
        ).json()
        t1.join(timeout=3)
        assert resp_e1["status"] == "completed"

    # Process Instance #2 (fresh memory, same disk SQLite archive + response_store_dir)
    app2 = create_app(_make_settings(tmp_path))
    post_restart_cmds = []
    with TestClient(app2) as client2, client2.websocket_connect("/ws/browser?client_id=ext-r") as ws2:
        ws2.receive_json()
        # Extension reports tab #301 is still sitting on url_e!
        ws2.send_json(
            {
                "type": "tab_status",
                "capabilities": ["multi_tab", "reset_tab", "open_session"],
                "tabs": [{"tab_id": 301, "tab_url": url_e, "ready": True}],
                "ready": True,
            }
        )
        ws2.receive_json()

        def w2():
            cmd = _recv_next_meaningful(ws2)
            post_restart_cmds.append(cmd)
            ws2.send_json(
                {
                    "type": "request_complete",
                    "request_id": cmd["request_id"],
                    "tab_id": 301,
                    "tab_url": url_e,
                    "reply": "E2-after-restart",
                }
            )

        t2 = threading.Thread(target=w2, daemon=True)
        t2.start()
        resp_e2 = client2.post(
            "/v1/responses",
            json={
                "model": "gemini-4-carbon",
                "previous_response_id": resp_e1["id"],
                "input": "RESTART_DELTA_FOLLOWUP",
            },
        ).json()
        t2.join(timeout=3)
        assert resp_e2["status"] == "completed"

    assert len(post_restart_cmds) == 1
    # Must NOT even need open_session or reset_chat because tab #301 was hydrated directly in place!
    assert post_restart_cmds[0]["type"] == "execute_prompt"
    assert post_restart_cmds[0]["tab_id"] == 301
    assert post_restart_cmds[0]["reset_chat"] is False
    assert "RESTART_SEED_HISTORY" not in post_restart_cmds[0]["prompt"]
    assert "RESTART_DELTA_FOLLOWUP" in post_restart_cmds[0]["prompt"]
