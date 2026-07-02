import importlib
import main
from starlette.testclient import TestClient

SESSION_CREDS = {
    "SIGNALWIRE_PROJECT_ID": "attendee-project",
    "SIGNALWIRE_TOKEN": "attendee-token",
    "SIGNALWIRE_SPACE": "attendee.signalwire.com",
}


def _own_client(monkeypatch):
    # Shared deployment + connected own account: verify runs on own creds.
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "p")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "t")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    client = TestClient(m.server.app, base_url="https://testserver")
    assert client.post("/api/credentials", json=SESSION_CREDS).status_code == 200
    assert client.get("/api/account").json().get("has_own") is True
    return client, m


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_verify_start_normalizes_pretty_input(monkeypatch):
    client, _ = _own_client(monkeypatch)
    seen = {}

    def fake_create(number, name=None, creds=None):
        seen["number"] = number
        return {"id": "vid-1", "verified": False}

    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "create_verified_caller_id", fake_create)
    r = client.post("/api/verify/start", json={"number": "(312) 555-0100"})
    assert r.status_code == 200
    assert seen["number"] == "+13125550100"
    _restore(monkeypatch)


def test_verify_start_rejects_implausible_number(monkeypatch):
    client, _ = _own_client(monkeypatch)
    r = client.post("/api/verify/start", json={"number": "12"})
    assert r.status_code == 400
    assert "phone number" in r.json()["error"].lower()
    _restore(monkeypatch)


def test_verify_needed_normalizes_to_param(monkeypatch):
    client, _ = _own_client(monkeypatch)
    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "account_is_trial", lambda creds=None: True)
    monkeypatch.setattr(step12, "list_verified_caller_ids",
                        lambda creds=None: [{"number": "+13125550100", "verified": True}])
    r = client.get("/api/verify/needed", params={"to": "(312) 555-0100"})
    assert r.status_code == 200
    assert r.json()["verified"] is True
    assert r.json()["needed"] is False
    _restore(monkeypatch)
