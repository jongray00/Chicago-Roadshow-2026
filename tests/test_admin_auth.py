"""The /admin dashboard (page, APIs, and stream) must require HTTP Basic auth so
attendee call data is not world-readable on a shared deployment."""
import base64
from starlette.testclient import TestClient
import main


def _client():
    return TestClient(main.server.app)


def _basic(user, pw):
    raw = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def test_admin_page_requires_auth():
    r = _client().get("/admin")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_admin_api_requires_auth():
    r = _client().get("/admin/calls")
    assert r.status_code == 401


def test_admin_page_ok_with_correct_creds():
    r = _client().get("/admin", headers=_basic(main._ADMIN_USER, main._ADMIN_PASSWORD))
    assert r.status_code == 200


def test_admin_rejects_wrong_password():
    r = _client().get("/admin", headers=_basic(main._ADMIN_USER, "definitely-wrong"))
    assert r.status_code == 401


def test_non_admin_route_is_open():
    # The landing page and curriculum stay public.
    assert _client().get("/api/curriculum").status_code == 200


def test_provision_agents_requires_admin_auth():
    # /api/admin/provision-agents lives OUTSIDE the /admin* middleware prefix;
    # only the in-handler _admin_auth_ok check guards it. Pin that gate directly.
    r = _client().post("/api/admin/provision-agents")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate", "").startswith("Basic")


def test_provision_agents_accepts_admin_auth(monkeypatch):
    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "provision_guided_agents", lambda public, creds: [])
    monkeypatch.setattr(main, "_require_public_base", lambda: "https://example.test")
    r = _client().post("/api/admin/provision-agents",
                        headers=_basic(main._ADMIN_USER, main._ADMIN_PASSWORD))
    assert r.status_code == 200
