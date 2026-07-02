"""Tests for GET /api/postprompt/final.

The store's real insert API is CallStore.record(agent_name, agent_route, raw_data),
which normalises the payload and stamps received_at = time.time().
We control ordering by monkeypatching call_store.time.time to return
deterministic values per call.
"""
from fastapi.testclient import TestClient


def test_postprompt_final_returns_latest_step11(monkeypatch):
    import call_store, main

    call_store.STORE.clear()

    # Patch time.time in the call_store module so received_at is deterministic.
    # We assign timestamps so the WINNER (/complete, received_at=300) is inserted
    # FIRST, then /step06 (received_at=200), then the OLDER /complete (received_at=100)
    # is inserted LAST.  Because the store inserts newest-first (_calls.insert(0, rec)),
    # calls[0] will be the OLDER /complete — so a naive "return calls[0]" would return
    # the wrong record.  Only correct max(received_at) logic picks the winner.
    _times = [300.0, 200.0, 100.0]
    _idx = [0]

    def _fake_time():
        val = _times[_idx[0] % len(_times)]
        _idx[0] += 1
        return val

    monkeypatch.setattr(call_store.time, "time", _fake_time)

    # Insert winner first (received_at=300), then a /step06 (received_at=200),
    # then the older /complete last (received_at=100).  After all inserts,
    # calls[0] == older11 — the wrong answer if the endpoint used calls[0].
    call_store.STORE.record("buddy", "/complete", {"call_id": "winner11",
        "post_prompt_data": {"raw": "winner"}})
    call_store.STORE.record("buddy", "/step06", {"call_id": "other",
        "post_prompt_data": {"raw": "x"}})
    call_store.STORE.record("buddy", "/complete", {"call_id": "older11",
        "post_prompt_data": {"raw": "old"}})

    client = TestClient(main.server.app)
    r = client.get("/api/postprompt/final")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    # Must be winner11 (received_at=300), not older11 (received_at=100, at calls[0]).
    assert body["call"]["call_id"] == "winner11"


def test_postprompt_final_empty_state(monkeypatch):
    import call_store, main

    call_store.STORE.clear()

    client = TestClient(main.server.app)
    r = client.get("/api/postprompt/final")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False and body["call"] is None
    # The definition graph ships even with no captured call, so the viewer
    # can show the full (dimmed) state machine.
    assert body["agent_graph"]["initial_step"] == "greeting"


def test_postprompt_final_includes_state_flow(monkeypatch):
    import call_store, main
    call_store.STORE.clear()
    call_store.STORE.record("complete-agent", "/complete", {
        "call_id": "sf1", "post_prompt_data": {"raw": "ok"},
        "call_log": [{"role": "system-log", "action": "step_change", "timestamp": 1,
                      "metadata": {"to_step": "weather", "trigger": "ai_function"}}],
    })
    r = TestClient(main.server.app).get("/api/postprompt/final")
    body = r.json()
    assert body["found"] is True
    assert body["call"]["state_flow"]["transitions"][0]["to_step"] == "weather"


def test_postprompt_final_includes_metrics_timeline():
    import call_store, main
    call_store.STORE.clear()
    call_store.STORE.record("complete-agent", "/complete", {
        "call_id": "mt1", "post_prompt_data": {"raw": "ok"},
        "ai_start_date": 1_000_000_000_000, "ai_end_date": 1_000_000_000_000 + 60_000_000,
        "call_log": [{"role": "assistant", "content": "hi", "audio_latency": 900, "timestamp": 1}],
    })
    from fastapi.testclient import TestClient
    body = TestClient(main.server.app).get("/api/postprompt/final").json()
    assert body["found"] is True
    assert "metrics" in body["call"] and "timeline" in body["call"]
    assert body["call"]["metrics"]["latency"]["assistant"]["count"] == 1


def test_postprompt_final_includes_charts():
    import call_store, main
    call_store.STORE.clear()
    call_store.STORE.record("complete-agent", "/complete", {
        "call_id": "charts-call",
        "call_log": [{"role": "assistant", "content": "hi", "latency": 900, "timestamp": 1}],
    })
    body = TestClient(main.server.app).get("/api/postprompt/final").json()
    assert body["found"] is True
    assert body["call"]["charts"]["latency_breakdown"][0]["total"] == 900
