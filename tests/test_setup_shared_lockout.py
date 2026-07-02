import importlib
import main
from starlette.testclient import TestClient

SESSION_CREDS = {
    "SIGNALWIRE_PROJECT_ID": "attendee-project",
    "SIGNALWIRE_TOKEN": "attendee-token",
    "SIGNALWIRE_SPACE": "attendee.signalwire.com",
}


def _shared_client(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "p")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "t")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    return TestClient(m.server.app, base_url="https://testserver"), m


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_setup_search_403_in_shared_mode(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/setup/search", json={"area_code": "312"})
    assert r.status_code == 403
    assert r.json().get("shared_mode") is True
    _restore(monkeypatch)


def test_setup_select_403_in_shared_mode(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/setup/select", json={"phone_number": "+13125550100", "route": "/hello"})
    assert r.status_code == 403
    _restore(monkeypatch)


def test_setup_route_403_in_shared_mode(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    r = client.post("/api/setup/route", json={"route": "/tool"})
    assert r.status_code == 403
    _restore(monkeypatch)


def test_setup_select_403_even_with_own_session_creds(monkeypatch):
    # Connecting your own account must NOT unlock the shared deployment's wizard:
    # the wizard has no role in shared mode (own numbers go through /api/own/*).
    client, _ = _shared_client(monkeypatch)
    assert client.post("/api/credentials", json=SESSION_CREDS).status_code == 200
    assert client.get("/api/account").json().get("has_own") is True
    r = client.post("/api/setup/select", json={"phone_number": "+13125550100", "route": "/hello"})
    assert r.status_code == 403
    _restore(monkeypatch)


def test_setup_search_still_works_off_shared_mode(monkeypatch):
    # Solo mode unchanged: missing creds yields the existing 400, not a 403.
    monkeypatch.delenv("WORKSHOP_SHARED_ACCOUNT", raising=False)
    for k in ("SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_TOKEN", "SIGNALWIRE_SPACE"):
        monkeypatch.delenv(k, raising=False)
    m = importlib.reload(main)
    client = TestClient(m.server.app)
    r = client.post("/api/setup/search", json={})
    assert r.status_code == 400
    _restore(monkeypatch)
