import importlib
import main
from starlette.testclient import TestClient


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_account_solo_when_opted_out(monkeypatch):
    # Shared/workshop account is the default when creds are present, so solo
    # (per-attendee) mode now requires the explicit WORKSHOP_SHARED_ACCOUNT=0
    # opt-out. (.env creds are loaded on reload, so the flag is what decides.)
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "0")
    m = importlib.reload(main)
    data = TestClient(m.server.app).get("/api/account").json()
    assert data["shared"] is False
    assert data["mode"] == "solo"
    _restore(monkeypatch)


def test_account_shared_when_flag_on_and_no_session_creds(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "p")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "t")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    data = TestClient(m.server.app).get("/api/account").json()
    assert data["shared"] is True
    assert data["mode"] == "shared"
    assert data["has_own"] is False
    _restore(monkeypatch)
