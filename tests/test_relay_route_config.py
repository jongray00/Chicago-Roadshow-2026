import importlib
import main
from starlette.testclient import TestClient


def _shared_client(monkeypatch):
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "shared-project")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "shared-token")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    return TestClient(m.server.app, base_url="https://testserver"), m


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_relay_config_rejects_invalid_routes(monkeypatch):
    client, _ = _shared_client(monkeypatch)
    for bad in ("/outbound", "/step06", "/nope", "complete"):
        r = client.get("/api/relay/config", params={"route": bad})
        assert r.status_code == 400, f"{bad} -> {r.status_code}"
    _restore(monkeypatch)


def test_relay_config_shared_uses_per_version_resource(monkeypatch):
    # Contract: in shared mode, a route param must resolve the PER-VERSION
    # resource name (agent_resource_name(route)), not the legacy single
    # HANDLER_NAME resource. `agent_address_by_name` is the seam that reads
    # both the address id and the dial destination from one addresses lookup
    # (see step12_rest_demo.agent_address_by_name / ensure_agent_handler's
    # channels selection, which this mirrors for an already-existing resource
    # found by name instead of created/updated by route).
    client, m = _shared_client(monkeypatch)
    seen = {}
    import python.steps.step12_rest_demo as step12

    def fake_agent_address_by_name(name, client=None, creds=None):
        seen["name"] = name
        # Non-vacuous: only the CORRECT per-version name yields a real
        # address; any other name (e.g. HANDLER_NAME) fails the lookup,
        # forcing the endpoint to 503 -- so a wrong name reaching here would
        # fail this test's 200/token assertions below.
        if name != step12.agent_resource_name("/tool"):
            return None, None
        return "addr-1", "/public/buddy-v2"

    monkeypatch.setattr(step12, "agent_address_by_name", fake_agent_address_by_name)
    monkeypatch.setattr(step12, "mint_guest_token", lambda address_id, creds=None: "tok-1")
    r = client.get("/api/relay/config", params={"route": "/tool"})
    assert r.status_code == 200
    assert seen["name"] == step12.agent_resource_name("/tool")
    body = r.json()
    assert body["token"] == "tok-1"
    assert body["destination"] == "/public/buddy-v2"
    _restore(monkeypatch)


def test_relay_config_shared_route_missing_resource_is_503(monkeypatch):
    # The per-version resource hasn't been provisioned yet (provision_guided_
    # agents never ran for this route) -> lookup returns (None, None) -> the
    # endpoint must surface a clear 503, not a stack trace or a 200 with junk.
    client, m = _shared_client(monkeypatch)
    import python.steps.step12_rest_demo as step12
    monkeypatch.setattr(step12, "agent_address_by_name", lambda name, client=None, creds=None: (None, None))
    r = client.get("/api/relay/config", params={"route": "/skills"})
    assert r.status_code == 503
    assert "not provisioned" in r.json()["error"]
    _restore(monkeypatch)


def test_relay_config_default_route_unchanged(monkeypatch):
    # No param -> the existing /complete ensure_agent_handler path, proven by
    # the same seams the pre-existing behavior uses.
    client, _ = _shared_client(monkeypatch)
    seen = {}
    import python.steps.step12_rest_demo as step12

    def fake_ensure_agent_handler(base, route, name, creds, session, sid):
        seen["route"] = route
        return "/public/complete"

    monkeypatch.setattr(step12, "ensure_agent_handler", fake_ensure_agent_handler)
    monkeypatch.setattr(step12, "agent_address_id", lambda client=None, creds=None, name=None: "addr-0")
    monkeypatch.setattr(step12, "mint_guest_token", lambda address_id, creds=None: "tok-0")
    r = client.get("/api/relay/config")
    assert r.status_code == 200
    assert seen["route"] == "/complete"
    body = r.json()
    assert body["token"] == "tok-0"
    assert body["destination"] == "/public/complete"
    _restore(monkeypatch)
