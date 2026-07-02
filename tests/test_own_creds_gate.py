import importlib
import main
from starlette.testclient import TestClient


def _shared_client(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "p")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "t")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    return TestClient(m.server.app), m


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_outbound_blocked_on_shared_account(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/outbound/call", json={"to": "+13125550123"})
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)


def test_verify_start_blocked_on_shared_account(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/verify/start", json={"number": "+13125550123"})
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)


def test_verify_confirm_blocked_on_shared_account(monkeypatch):
    # confirm completes phone ownership — must be gated too.
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/verify/confirm", json={"id": "vid", "code": "123456"})
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)


def test_verify_redial_blocked_on_shared_account(monkeypatch):
    # redial triggers a verification call — must be gated too.
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/verify/redial", json={"id": "vid"})
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)


def test_verify_status_blocked_on_shared_account(monkeypatch):
    # status reads must also stay gated — a fresh session has no own creds.
    client, _ = _shared_client(monkeypatch)
    r = client.get("/api/verify/status")
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)


def test_own_numbers_blocked_on_shared_account(monkeypatch):
    # the post-login number picker must not fall back to the shared env creds.
    client, _ = _shared_client(monkeypatch)
    r = client.get("/api/own/numbers")
    assert r.status_code == 400
    assert r.json().get("needs_own_account") is True
    _restore(monkeypatch)
