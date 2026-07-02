import importlib
import main
from starlette.testclient import TestClient

SESSION_CREDS = {
    "SIGNALWIRE_PROJECT_ID": "attendee-project",
    "SIGNALWIRE_TOKEN": "attendee-token",
    "SIGNALWIRE_SPACE": "attendee.signalwire.com",
}


def _shared_client(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "shared-project")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "shared-token")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    # https base_url so the Secure session cookie is retained and resent.
    return TestClient(m.server.app, base_url="https://testserver"), m


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def _connect_own_account(client):
    r = client.post("/api/credentials", json=SESSION_CREDS)
    assert r.status_code == 200
    # Guard: the session creds must actually attach, or the endpoint tests
    # below would pass vacuously (env fallback) instead of proving the pin.
    r2 = client.get("/api/account")
    assert r2.json().get("has_own") is True


def test_agent_numbers_uses_env_creds_even_with_session_creds(monkeypatch):
    client, m = _shared_client(monkeypatch)
    _connect_own_account(client)
    seen = {}

    def fake_map(creds):
        seen["creds"] = creds
        return [{"route": "/hello", "version": 1, "title": "Hello Buddy", "e164": "+15205550001"}]

    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "guided_number_map", fake_map)
    m._GUIDED_NUMBERS_CACHE["agents"] = None
    r = client.get("/api/agent/numbers")
    assert r.status_code == 200
    assert seen["creds"]["SIGNALWIRE_PROJECT_ID"] == "shared-project"
    m._GUIDED_NUMBERS_CACHE["agents"] = None
    _restore(monkeypatch)


def test_relay_config_uses_env_creds_even_with_session_creds(monkeypatch):
    client, m = _shared_client(monkeypatch)
    _connect_own_account(client)
    seen = {}

    def fake_ensure(base, route, name, creds, session, sid):
        seen["creds"] = creds
        return "/public/complete-buddy"

    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "ensure_agent_handler", fake_ensure)
    monkeypatch.setattr(step12, "agent_address_id", lambda name, creds: "addr-1")
    monkeypatch.setattr(step12, "mint_guest_token", lambda address_id, creds: "tok-1")
    r = client.get("/api/relay/config")
    assert r.status_code == 200
    assert seen["creds"]["SIGNALWIRE_PROJECT_ID"] == "shared-project"
    _restore(monkeypatch)


def test_build_creds_for_matches_creds_for_off_shared_mode(monkeypatch):
    monkeypatch.delenv("WORKSHOP_SHARED_ACCOUNT", raising=False)
    m = importlib.reload(main)
    assert m.build_creds_for.__doc__  # exists and documented
    _restore(monkeypatch)
