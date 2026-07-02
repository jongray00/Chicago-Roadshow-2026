"""Replit-proofing: bases and auth must resolve DYNAMICALLY.

Two past incidents drive these tests:
1. A persisted quick-tunnel public_base override outlived its tunnel and
   silently broke every webhook URL (three separate sightings).
2. The admin gate froze an empty password at import time, which disabled the
   middleware AND made the in-handler check unpassable for the whole process.
"""
import importlib
import json

import config_store
import main
from starlette.testclient import TestClient


def _store(tmp_path, **data):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(data))
    st = config_store.ConfigStore(str(path))
    st.load()
    return st


def test_stale_quick_tunnel_override_dropped(tmp_path, monkeypatch):
    # importing main exports SWML_PROXY_URL_BASE into os.environ; isolate
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    st = _store(tmp_path,
                public_base="https://old-dead-words.trycloudflare.com",
                detected_base="https://fresh-live-words.trycloudflare.com")
    assert st.drop_stale_quick_tunnel() is True
    assert st.effective_base() == "https://fresh-live-words.trycloudflare.com"


def test_custom_domain_override_kept(tmp_path, monkeypatch):
    # Deliberate operator intent (a real domain) is never auto-dropped.
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    st = _store(tmp_path,
                public_base="https://workshop.example.com",
                detected_base="https://fresh-live-words.trycloudflare.com")
    assert st.drop_stale_quick_tunnel() is False
    assert st.effective_base() == "https://workshop.example.com"


def test_matching_quick_tunnel_override_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    st = _store(tmp_path,
                public_base="https://same-words.trycloudflare.com",
                detected_base="https://same-words.trycloudflare.com")
    assert st.drop_stale_quick_tunnel() is False


def test_quick_tunnel_dropped_on_replit_detection(tmp_path, monkeypatch):
    # The Replit case: detection finds the repl domain; a leftover local
    # quick-tunnel override must not win.
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    st = _store(tmp_path,
                public_base="https://old-dead-words.trycloudflare.com",
                detected_base="https://my-workshop.repl.co")
    assert st.drop_stale_quick_tunnel() is True
    assert st.effective_base() == "https://my-workshop.repl.co"


def test_admin_password_tracks_live_swml_password(monkeypatch):
    # The gate must follow the CURRENT effective SWML password, not a value
    # frozen at import. Simulate a live password change through the config
    # store and confirm the gate moves with it.
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    m = importlib.reload(main)
    client = TestClient(m.server.app, base_url="https://testserver")
    import base64

    def basic(user, pw):
        return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}

    old_pw = m._admin_password()
    assert old_pw, "gate must never be open by default"
    assert client.get("/admin", headers=basic("admin", old_pw)).status_code == 200
    m._CONFIG.update(auth_password="rotated-live-secret")
    try:
        assert m._admin_password() == "rotated-live-secret"
        assert client.get("/admin", headers=basic("admin", old_pw)).status_code == 401
        assert client.get("/admin", headers=basic("admin", "rotated-live-secret")).status_code == 200
    finally:
        m._CONFIG.update(auth_password="")   # restore: fall back to env/default
    monkeypatch.undo()
    importlib.reload(main)


def test_env_export_cannot_launder_stale_override(tmp_path, monkeypatch):
    # The observed incident: _apply_config exports the effective base into
    # SWML_PROXY_URL_BASE. If ranking read the LIVE env, a stale override
    # would survive its own clearing (override -> env -> forever). Ranking
    # must only see the launch-time env captured at construction.
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    st = _store(tmp_path,
                public_base="https://old-dead-words.trycloudflare.com",
                detected_base="https://fresh-live-words.trycloudflare.com")
    # simulate _apply_config's export of the (stale) effective base
    monkeypatch.setenv("SWML_PROXY_URL_BASE", st.effective_base())
    st.update(public_base="")                     # operator clears the override
    assert st.effective_base() == "https://fresh-live-words.trycloudflare.com"
    assert st.snapshot()["public_base"] == "https://fresh-live-words.trycloudflare.com"
