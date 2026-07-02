import base64
import main
from starlette.testclient import TestClient

client = TestClient(main.server.app)


def _auth_headers():
    import os
    user = os.environ.get("SWML_BASIC_AUTH_USER", "workshop")
    pw = os.environ.get("SWML_BASIC_AUTH_PASSWORD", "password")
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {tok}"}


LEGACY_TO_CURRENT = {
    "/step04": "/hello",
    "/step08": "/tool",
    "/step10": "/skills",
    "/step11": "/complete",
}


def test_legacy_routes_serve_swml():
    # Pre-rename SWML webhooks in the wild must keep working after the deploy.
    # NOTE: agent roots are mounted, so the trailing slash is required (see
    # tests/test_routes.py::test_step_route_returns_swml, which does the same
    # for the current routes) -- this is pre-existing SDK behavior, not
    # something introduced by the alias.
    for legacy in LEGACY_TO_CURRENT:
        r = client.get(f"{legacy}/", headers=_auth_headers())
        assert r.status_code == 200, f"{legacy} -> {r.status_code}"
        assert "sections" in r.json(), f"{legacy} did not return SWML"


def test_aliases_live_in_alias_agents_not_registered_agents():
    # Aliases must NOT sit in registered_agents: the function-health
    # registration loop and the admin SWAIG iteration key off it, and alias
    # instances there produce duplicate health rows (/step08 next to /tool).
    # They live in ALIAS_AGENTS instead so config sync can still reach them.
    for legacy in LEGACY_TO_CURRENT:
        assert legacy not in main.registered_agents, f"{legacy} leaked into registered_agents"
        assert legacy in main.ALIAS_AGENTS, f"{legacy} missing from ALIAS_AGENTS"


def test_health_registration_excludes_alias_routes(tmp_path):
    # Replay main's function-health registration source (registered_agents)
    # into a FRESH store: no alias route may produce a row. A fresh store is
    # required because the module-level STORE replays persisted legacy rows
    # from disk, which would confound the check.
    from function_health import FunctionHealth
    fh = FunctionHealth(path=str(tmp_path / "h.json"))
    for _route, _agent in main.registered_agents.items():
        reg = getattr(getattr(_agent, "_tool_registry", None), "_swaig_functions", {}) or {}
        for _fname in reg:
            fh.register(_fname, route=_route)
    routes = {r["route"] for r in fh.all()}
    assert routes.isdisjoint(LEGACY_TO_CURRENT.keys()), routes


def test_apply_config_keeps_alias_basic_auth_in_sync():
    import os
    main._apply_config()
    user = os.environ["SWML_BASIC_AUTH_USER"]
    pw = os.environ["SWML_BASIC_AUTH_PASSWORD"]
    for legacy, agent in main.ALIAS_AGENTS.items():
        assert agent._basic_auth == (user, pw), f"{legacy} basic auth out of sync"


def test_postprompt_final_includes_alias_route_calls():
    # Call records are tagged with the route they were SERVED on. A call that
    # arrives through the /step11 alias (a pre-rename webhook -- exactly what
    # the alias exists to support) must still surface in the finale showcase.
    import call_store
    call_store.STORE.clear()
    call_store.STORE.record("complete-agent", "/step11", {
        "call_id": "alias-call-1",
        "post_prompt_data": {"raw": "arrived via legacy /step11 webhook"},
    })
    r = client.get("/api/postprompt/final")
    body = r.json()
    assert body["found"] is True, body
    assert body["call"]["call_id"] == "alias-call-1"


def test_legacy_routes_hidden_from_curriculum():
    # /api/curriculum returns {"guided": [...], "capstone": {...}} (see
    # tests/test_curriculum.py) -- not a flat "steps" list. Aliases must not
    # appear in either.
    r = client.get("/api/curriculum")
    data = r.json()
    routes = {s["route"] for s in data["guided"]}
    routes.add(data["capstone"]["route"])
    assert routes.isdisjoint(LEGACY_TO_CURRENT.keys())
