#!/usr/bin/env python3
"""
SignalWire AI Agent Workshop - Replit Edition
=============================================
Serves all workshop step agents simultaneously on separate routes,
plus a landing page at / with workshop info, SWML URLs, and setup instructions.

Add your optional Secrets, click Run, and open the web preview.

DEPLOYMENT NOTES (Replit Autoscale)
------------------------------------
1. The deploy URL is hardcoded in replit_setup.py (DEPLOY_URL).
   Update it there if the Replit app name changes.

2. After ANY code change, manually redeploy:
   Deployments tab -> Redeploy. Autoscale does NOT auto-redeploy on git push.

3. Verify deployment: GET https://<deployed-url>/validate
   All agents should show swaig_url_valid: true.

4. Run full test suite: python test_routes.py https://<deployed-url>
"""

import asyncio
import base64
import json
import logging
import os
import secrets
import signal
import sys
import uuid
from replit_setup import startup
import session_store
import call_store
import config_store
import agent_graph
from urllib.parse import urlparse


def _load_dotenv(path=".env"):
    """Local-dev convenience: load KEY=VALUE lines from a .env into os.environ.

    Only used for local testing. The file is gitignored and never deployed, so
    on Replit (which uses the Secrets tab) it simply does not exist and this is
    a no-op -- meaning workshop attendees are still prompted for their own
    credentials. Existing env vars are NEVER overwritten, so real environment
    variables / Replit Secrets always win over the file.
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value


# Load local .env (if present) BEFORE startup so credentials are available for
# the credentials-status endpoint and the panel auto-collapses during local dev.
# Guard: only load once per process so that importlib.reload (used in tests to
# swap env vars) does not re-read the file and undo monkeypatched deletions.
if not os.environ.get("_DOTENV_LOADED"):
    _load_dotenv()
    os.environ["_DOTENV_LOADED"] = "1"

_SESSIONS = session_store.SessionStore(path=".workshop_sessions.json")
_SESSIONS.load()

# Runtime config (public URL + SWAIG basic auth), editable on the admin page
# instead of via Replit Secrets. Applied into the live process by _apply_config().
_CONFIG = config_store.ConfigStore(path=".workshop_config.json")
_CONFIG.load()


def _resolve_session_for_call(raw_data):
    """Map a post-prompt payload to its originating session.

    1. Prefer global_data.workshop_session_id (exact; stamped at SWML render).
    2. Match the SignalWire project_id (every post-prompt payload carries it;
       each attendee uses their own project). This is the reliable workhorse —
       confirmed against a real captured payload.
    3. Fall back to matching the provisioned phone number against to/from.
    Defensive: returns None on any mismatch and never raises.
    """
    try:
        raw_data = raw_data if isinstance(raw_data, dict) else {}

        gd = raw_data.get("global_data") or {}
        sid = gd.get("workshop_session_id") if isinstance(gd, dict) else None
        if sid:
            sess = _SESSIONS.get(sid)
            if sess:
                creds = sess.get("creds", {}) or {}
                return {"space": creds.get("SIGNALWIRE_SPACE"),
                        "project_id": creds.get("SIGNALWIRE_PROJECT_ID"),
                        "session_id": sid}

        project_id = raw_data.get("project_id")
        if project_id:
            for row in _SESSIONS.admin_snapshot():
                if row.get("project_id") == project_id:
                    return {"space": row["space"], "project_id": row["project_id"],
                            "session_id": row["session_id"]}

        swml = raw_data.get("SWMLVars") or raw_data.get("prompt_vars") or {}
        if not isinstance(swml, dict):
            swml = {}
        candidates = {swml.get("to"), swml.get("from"), raw_data.get("caller_id_num")}
        candidates.discard(None)
        for row in _SESSIONS.admin_snapshot():
            setup_num = row.get("agent_address") or ""
            sess = _SESSIONS.get(row["session_id"]) or {}
            provisioned = (sess.get("setup", {}) or {}).get("phone_number")
            if (provisioned and provisioned in candidates) or (setup_num and setup_num in candidates):
                return {"space": row["space"], "project_id": row["project_id"],
                        "session_id": row["session_id"]}
    except Exception:
        return None
    return None


call_store.set_session_resolver(_resolve_session_for_call)


def _resolve_live_event_session(call_info):
    """Map a Live Wire debug-event call_info to its attendee session.

    Live debug payloads carry call_info.project_id (not global_data), so we
    correlate the same way post-prompt does: the attendee using that project.
    Defensive — returns None on any miss and never raises.
    """
    try:
        pid = call_info.get("project_id") if isinstance(call_info, dict) else None
        if not pid:
            return None
        for row in _SESSIONS.admin_snapshot():
            if row.get("project_id") == pid:
                return row["session_id"]
    except Exception:
        return None
    return None


import live_events as _live_events
_live_events.set_session_resolver(_resolve_live_event_session)

# Detect public URL and report secret status (no longer blocks on missing creds)
base_url, auth_user, auth_pass = startup()

# ---------------------------------------------------------------------------
# SDK imports
# ---------------------------------------------------------------------------
from signalwire_agents import AgentServer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse, JSONResponse, FileResponse, StreamingResponse

from python.steps.step04_hello import HelloAgent
from python.steps.step06_hardcoded_jokes import JokeAgent as HardcodedJokeAgent
from python.steps.step07_api_jokes import JokeAgent as ApiJokeAgent
from python.steps.step08_weather import WeatherJokeAgent
from python.steps.step09_polish import PolishedAgent
from python.steps.step10_skills import SkillsAgent
from python.steps.step11_complete import CompleteAgent
from python.steps.step14_outbound import OutboundAgent

# ---------------------------------------------------------------------------
# Register all step agents on their own routes
# ---------------------------------------------------------------------------

# Routes are semantic slugs that match each agent's guided version, so the SWML
# URL an attendee sees always agrees with the version label (no "/step11" behind
# "Version 4"). Archived agents keep their historical /stepNN routes -- they are
# hidden from the UI and their labels are marked "Archived" so no two entries
# ever read the same version number.
STEPS = [
    ("/hello",    HelloAgent,          "Version 1 - Hello Buddy"),
    ("/step06",   HardcodedJokeAgent,  "Archived - Hardcoded Jokes"),
    ("/step07",   ApiJokeAgent,        "Archived - Live API Jokes"),
    ("/tool",     WeatherJokeAgent,    "Version 2 - Buddy Gets a Tool"),
    ("/step09",   PolishedAgent,       "Archived - Polished Agent"),
    ("/skills",   SkillsAgent,         "Version 3 - Buddy Gets Skills"),
    ("/complete", CompleteAgent,       "Version 4 - Complete Buddy"),
    ("/outbound", OutboundAgent,       "Outbound - Outbound Buddy"),
]

# The guided rebuild path the UI shows: four versions, additive. Archived agents
# (/step06, /step07, /step09) stay registered above but are absent here, so the
# learning-path UI never lists them. The outbound capstone is presented once,
# after the four build steps are complete.
GUIDED_STEPS = [
    {"id": "hello",    "route": "/hello",    "title": "Hello Buddy",       "version": 1},
    {"id": "tool",     "route": "/tool",     "title": "Buddy Gets a Tool", "version": 2},
    {"id": "skills",   "route": "/skills",   "title": "Buddy Gets Skills", "version": 3},
    {"id": "complete", "route": "/complete", "title": "Complete Buddy",    "version": 4},
]
OUTBOUND_CAPSTONE = {"id": "outbound", "route": "/outbound", "title": "Outbound Buddy"}

server = AgentServer(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

# Each agent must know its route so the SDK generates correct webhook URLs
# (e.g., /step06/swaig/ not /swaig/).  We pass route= through the constructor
# so it's set during super().__init__() - the SDK's intended pattern.
registered_agents = {}
for route, agent_class, _desc in STEPS:
    agent = agent_class(route=route)
    server.register(agent, route)
    registered_agents[route] = agent

# Legacy aliases: the 2026-07 semantic rename (/step04 -> /hello etc.) must not
# break SWML webhooks provisioned before it (the live shared resource and any
# attendee-account resources). Each alias is a separate instance constructed
# with the LEGACY route so its own webhook URLs are self-consistent. Aliases
# are registered on the server but never listed (absent from STEPS /
# GUIDED_STEPS) and kept OUT of registered_agents: the function-health
# registration and admin SWAIG dispatch iterate registered_agents, and alias
# instances there would surface duplicate health rows (/step08 next to /tool).
# ALIAS_AGENTS exists so config sync and startup URL validation still reach
# them.
LEGACY_ROUTE_ALIASES = {
    "/step04": HelloAgent,
    "/step08": WeatherJokeAgent,
    "/step10": SkillsAgent,
    "/step11": CompleteAgent,
}
ALIAS_AGENTS = {}
for _legacy_route, _legacy_cls in LEGACY_ROUTE_ALIASES.items():
    _alias = _legacy_cls(route=_legacy_route)
    server.register(_alias, _legacy_route)
    ALIAS_AGENTS[_legacy_route] = _alias


def _effective_base():
    """Public URL SignalWire calls back: admin override -> auto-detected -> env."""
    return _CONFIG.effective_base(env_default=base_url)


def _apply_config():
    """Push the effective config into the live process so edits take effect now:
    - SWML_PROXY_URL_BASE env: used by step12 provisioning and the SDK's webhook
      URL generation.
    - SWML_BASIC_AUTH_* env + each agent's `_basic_auth` tuple: the agents both
      EMBED these creds in the webhook URLs they generate AND VALIDATE inbound
      SignalWire requests against them, so both sides must update together.
    """
    base = _effective_base()
    if base:
        os.environ["SWML_PROXY_URL_BASE"] = base
    user, pw = _CONFIG.effective_auth()
    os.environ["SWML_BASIC_AUTH_USER"] = user
    os.environ["SWML_BASIC_AUTH_PASSWORD"] = pw
    # Aliases live outside registered_agents (see ALIAS_AGENTS above) but
    # validate inbound basic auth exactly like listed agents, so both dicts
    # must stay in sync.
    for _agent in list(registered_agents.values()) + list(ALIAS_AGENTS.values()):
        try:
            _agent._basic_auth = (user, pw)
        except Exception:  # noqa: BLE001 - never let config application crash a request
            pass


_CONFIG.drop_stale_quick_tunnel(env_default=base_url)  # ephemeral-tunnel guard
_apply_config()  # apply any persisted overrides at startup

# ---------------------------------------------------------------------------
# Phase 3 observability: register every agent's SWAIG functions with the health
# store so /admin/swaig can list + run them. All functions now run in-process
# (define_tool); a dict registry entry would be a serverless DataMap.
# ---------------------------------------------------------------------------
import function_health
import error_store
import creds_normalize
from swaig_cases import CASES, expect_ok

def _fn_kind(fobj):
    """Classify a registry entry: ('datamap'|'skill'|'tool', skill_name|None).

    A dict entry is a serverless DataMap. A handler bound to a SkillBase
    instance was registered by an SDK skill (datetime, math); anything else is
    a custom define_tool function.
    """
    from signalwire_agents.core.skill_base import SkillBase
    if isinstance(fobj, dict):
        return "datamap", None
    owner = getattr(getattr(fobj, "handler", None), "__self__", None)
    if isinstance(owner, SkillBase):
        return "skill", getattr(owner, "SKILL_NAME", None) or type(owner).__name__
    return "tool", None


# Every (route, function) pair gets its own health row: tell_joke alone has
# three different implementations (/step06 hardcoded, /step07 live API,
# /complete state-machine), and each must be visible and testable on its own.
for _route, _agent in registered_agents.items():
    _reg = getattr(getattr(_agent, "_tool_registry", None), "_swaig_functions", {}) or {}
    for _fname, _fobj in _reg.items():
        _kind, _skill = _fn_kind(_fobj)
        function_health.STORE.register(_fname, route=_route, kind=_kind, skill=_skill)

# ---------------------------------------------------------------------------
# Config endpoint - landing page fetches auth credentials dynamically
# ---------------------------------------------------------------------------

@server.app.get("/api/curriculum")
async def curriculum():
    return JSONResponse({"guided": GUIDED_STEPS, "capstone": OUTBOUND_CAPSTONE})


@server.app.get("/config")
async def get_config():
    """Return non-sensitive config for the landing page JS."""
    return JSONResponse({
        "auth_user": auth_user,
        "auth_pass": auth_pass,
        "base_url": base_url,
    })

# ---------------------------------------------------------------------------
# Validate endpoint - verify all webhook URLs have correct route prefixes
# ---------------------------------------------------------------------------

@server.app.get("/validate")
async def validate_urls():
    """Check every agent's webhook URLs include the correct route prefix."""
    results = []
    all_valid = True
    for route, _cls, desc in STEPS:
        agent = registered_agents.get(route)
        if not agent:
            results.append({"route": route, "error": "agent not registered"})
            all_valid = False
            continue

        swaig_url = agent._build_webhook_url("swaig")
        post_url = agent._build_webhook_url("post_prompt")

        # Mask credentials for display
        def mask(url):
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url)
            if p.username:
                netloc = f"{p.username}:****@{p.hostname}"
                if p.port:
                    netloc += f":{p.port}"
                return urlunparse(p._replace(netloc=netloc))
            return url

        swaig_ok = route in swaig_url
        post_ok = route in post_url
        if not swaig_ok or not post_ok:
            all_valid = False

        func_names = []
        if hasattr(agent, '_tool_registry') and hasattr(agent._tool_registry, '_swaig_functions'):
            func_names = list(agent._tool_registry._swaig_functions.keys())

        results.append({
            "route": route,
            "name": agent.get_name(),
            "description": desc,
            "swaig_url": mask(swaig_url),
            "post_prompt_url": mask(post_url),
            "swaig_url_valid": swaig_ok,
            "post_prompt_url_valid": post_ok,
            "functions": func_names,
        })

    return JSONResponse({
        "status": "ok" if all_valid else "error",
        "base_url": base_url,
        "agent_count": len(results),
        "agents": results,
    })

# ---------------------------------------------------------------------------
# SWAIG/post_prompt fallback - catches calls when URL generation omits the
# step prefix (e.g., /swaig/ instead of /step06/swaig/).  Dispatches to the
# correct agent by matching the function name in the request body.
# ---------------------------------------------------------------------------

from fastapi import Request, Response, HTTPException
import json as _json
import time as _time


# In-process cache of the version->number mapping so we don't hit the Relay API
# on every page load. Cleared by a successful provision.
_GUIDED_NUMBERS_CACHE = {"agents": None}


@server.app.get("/api/agent/numbers")
async def agent_numbers(request: Request):
    """Version -> dedicated PSTN number mapping so each guided card can show
    'call this number'. Only meaningful in shared mode, where each version has
    its own dedicated number on the shared workshop account."""
    if not shared_account_active():
        return JSONResponse({"shared": False, "agents": []})
    if _GUIDED_NUMBERS_CACHE["agents"] is None:
        from python.steps.step12_rest_demo import guided_number_map
        try:
            mapping = await asyncio.to_thread(guided_number_map, build_creds_for(request))
        except Exception as e:  # noqa: BLE001 - never let the landing page fail on this
            logging.getLogger(__name__).warning("guided_number_map failed: %s", e)
            return JSONResponse({"shared": True, "agents": []})
        _GUIDED_NUMBERS_CACHE["agents"] = [
            {"route": m["route"], "version": m["version"], "title": m["title"], "e164": m["e164"]}
            for m in mapping
        ]
    return JSONResponse({"shared": True, "agents": _GUIDED_NUMBERS_CACHE["agents"]})


@server.app.post("/api/admin/provision-agents")
async def provision_agents(request: Request):
    """Admin-only: give each guided version its own resource + dedicated number.
    Idempotent. Behind the same basic auth as /admin."""
    if not _admin_auth_ok(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="admin"'})
    from python.steps.step12_rest_demo import provision_guided_agents
    try:
        public = _require_public_base()
        mapping = await asyncio.to_thread(
            provision_guided_agents, public, build_creds_for(request)
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    _GUIDED_NUMBERS_CACHE["agents"] = [
        {"route": m["route"], "version": m["version"], "title": m["title"], "e164": m["e164"]}
        for m in mapping
    ]
    return JSONResponse({"ok": True, "agents": _GUIDED_NUMBERS_CACHE["agents"]})


@server.app.get("/api/own/numbers")
async def own_numbers(request: Request):
    """Numbers on the attendee's OWN account, for the post-login number picker.
    Also returns a buy_url so a numberless account can go purchase one."""
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    from python.steps.step12_rest_demo import list_account_numbers
    try:
        nums = await asyncio.to_thread(list_account_numbers, creds)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    space = creds.get("SIGNALWIRE_SPACE", "") or ""
    host = space if space.startswith("http") else ("https://" + space)
    return JSONResponse({"numbers": nums, "space": space,
                         "buy_url": host.rstrip("/") + "/phone_numbers"})


@server.app.post("/api/own/use-number")
async def own_use_number(request: Request):
    """Point the attendee's chosen number at Buddy (inbound) on their OWN
    account, and remember it as the outbound from-number for this session."""
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    raw = await request.body()
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    number = _normalize_e164((body or {}).get("number", ""))
    if not number:
        return JSONResponse({"error": "a valid number is required"}, status_code=400)
    from python.steps.step12_rest_demo import assign_number_to_agent
    try:
        public = _require_public_base()
        await asyncio.to_thread(
            assign_number_to_agent, number, public, FINAL_VERSION_ROUTE,
            None, creds, request.state.session_id,
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    session = _SESSIONS.ensure(request.state.session_id)
    session.setdefault("setup", {})["phone_number"] = number
    _SESSIONS.save()
    return JSONResponse({"ok": True, "number": number, "route": FINAL_VERSION_ROUTE})


def _owning_agent(func_name):
    """Return the registered agent that owns `func_name`, or None."""
    for _route, agent in registered_agents.items():
        reg = getattr(getattr(agent, "_tool_registry", None), "_swaig_functions", None)
        if reg and func_name in reg:
            return _route, agent
    return None, None


def _swaig_result_failed(raw):
    """True if a SWAIG result dict represents a failure. The SDK swallows
    handler exceptions and returns HTTP 200 with an error payload, so we must
    inspect the result rather than rely on a raised exception."""
    if not isinstance(raw, dict):
        return False
    if raw.get("error"):
        return True
    resp = raw.get("response")
    if isinstance(resp, str) and (
        resp.startswith("Error executing function")
        or resp.startswith("Function '") and "not found" in resp
    ):
        return True
    return False


def run_swaig_case(func_name, route=None):
    """Invoke one SWAIG function against its swaig_cases entry and record health.

    `route` selects WHICH agent's implementation runs (tell_joke alone has three
    different implementations). Without a route, the first owning agent is used
    (back-compat for callers that predate per-route rows). Every workshop
    function runs in-process, so this always dispatches via
    agent._execute_swaig_function(...). Returns a verdict dict the /admin "Run
    test" button renders: {"ok", "result", "latency_ms"}.
    """
    case = next((c for c in CASES if c["function"] == func_name), None)
    args = case.get("args", {}) if case else {}
    expect = case.get("expect", "") if case else ""

    if route:
        agent = registered_agents.get(route)
        reg = getattr(getattr(agent, "_tool_registry", None), "_swaig_functions", None) if agent else None
        if not reg or func_name not in reg:
            error_store.STORE.record(source="swaig-test",
                                     message=f"unknown function: {func_name} on {route}")
            return {"ok": False, "result": f"function '{func_name}' not registered on {route}",
                    "latency_ms": None}
    else:
        route, agent = _owning_agent(func_name)
        if agent is None:
            # No owning agent: do NOT record_result (that would setdefault a phantom
            # entry into the function list and persist it). Just log the error.
            error_store.STORE.record(source="swaig-test", message=f"unknown function: {func_name}")
            return {"ok": False, "result": f"function '{func_name}' not registered", "latency_ms": None}

    # Defensive: a dict registry entry would be a serverless DataMap (runs on
    # SignalWire, not here). None remain today, but keep the branch honest.
    reg_entry = agent._tool_registry._swaig_functions.get(func_name)
    if isinstance(reg_entry, dict):
        detail = "DataMap (runs on SignalWire)"
        function_health.STORE.record_result(func_name, ok=True, detail=detail,
                                            latency_ms=None, route=route)
        return {"ok": True, "result": detail, "latency_ms": None}

    t0 = _time.perf_counter()
    try:
        raw = agent._execute_swaig_function(func_name, dict(args), None, None)
        text = raw.get("response") if isinstance(raw, dict) else (getattr(raw, "response", None) or str(raw))
        latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
        # The SDK swallows handler exceptions and returns an HTTP-200 error
        # string in `response`; that string is non-empty, so without this check
        # a crashing handler would be wrongly marked ok.
        failed = _swaig_result_failed(raw)
        ok = (not failed) and bool(text) and (not expect or expect_ok(text, expect))
        function_health.STORE.record_result(func_name, ok=ok, detail=text or "",
                                            latency_ms=latency_ms, route=route)
        return {"ok": ok, "result": text, "latency_ms": latency_ms}
    except Exception as e:  # noqa: BLE001 - a failing test must never crash the server
        latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
        msg = f"{e.__class__.__name__}: {e}"
        function_health.STORE.record_result(func_name, ok=False, detail=msg,
                                            latency_ms=latency_ms, route=route)
        error_store.STORE.record(source="swaig-test", message=f"{func_name}: {e}")
        return {"ok": False, "result": msg, "latency_ms": latency_ms}


@server.app.post("/swaig")
@server.app.post("/swaig/")
async def root_swaig_fallback(request: Request):
    """Dispatch SWAIG calls that land on root /swaig/ to the correct agent."""
    body = await request.body()
    try:
        data = _json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    func_name = data.get("function", "")

    # Find the agent that owns this function
    for _route, agent in registered_agents.items():
        if hasattr(agent, '_tool_registry') and hasattr(agent._tool_registry, '_swaig_functions'):
            if func_name in agent._tool_registry._swaig_functions:
                result = agent._execute_swaig_function(func_name, data, None, None)
                # The SDK never lets handler exceptions escape; it returns an
                # HTTP-200 error payload. Inspect the result to record failures.
                if _swaig_result_failed(result):
                    detail = str(result.get("error") or result.get("response"))
                    error_store.STORE.record(source="swaig", message=f"{func_name}: " + detail[:200])
                    function_health.STORE.record_result(
                        func_name, ok=False, detail=detail[:500], latency_ms=None)
                # Still return the result — SignalWire must receive the response.
                return JSONResponse(result if isinstance(result, dict) else {"response": str(result)})

    error_store.STORE.record(source="swaig", message=f"unknown function: {func_name}")
    raise HTTPException(status_code=404, detail="Function not found")

@server.app.post("/post_prompt")
@server.app.post("/post_prompt/")
async def root_post_prompt_fallback(request: Request):
    """Capture post_prompt calls that land on the root path."""
    body = await request.body()
    try:
        data = _json.loads(body)
    except Exception:
        data = {}
    agent_name = data.get("app_name") or data.get("agent") or "(root fallback)"
    call_store.STORE.record(agent_name, None, data)
    return JSONResponse({"status": "ok"})

# ---------------------------------------------------------------------------
# Admin dashboard — live post-prompt + sessions view (unlisted, no auth).
# ---------------------------------------------------------------------------

@server.app.get("/admin/calls")
async def admin_calls(request: Request):
    return JSONResponse({"calls": call_store.STORE.all()})


@server.app.get("/admin/sessions")
async def admin_sessions(request: Request):
    return JSONResponse({"sessions": _SESSIONS.admin_snapshot()})


@server.app.delete("/admin/calls")
async def admin_clear_calls(request: Request):
    call_store.STORE.clear()
    return JSONResponse({"status": "cleared"})


@server.app.get("/admin/export")
async def admin_export(request: Request):
    return JSONResponse(
        {"calls": call_store.STORE.all()},
        headers={"Content-Disposition": "attachment; filename=postprompt-calls.json"},
    )


FINAL_VERSION_ROUTE = "/complete"  # Version 4 "Complete Buddy"

# Call records are tagged with the route they were SERVED on, and the /step11
# legacy alias serves the same CompleteAgent to pre-rename webhooks. Any check
# that asks "did this CALL come from the final Buddy?" must accept both routes.
# Derived from ALIAS_AGENTS (not hardcoded) so alias changes stay in sync.
# NOTE: sites that TARGET the final agent (number pointing, provisioning,
# agent-graph lookups) keep using FINAL_VERSION_ROUTE -- new resources must
# point at the canonical route only.
FINAL_ROUTES = {FINAL_VERSION_ROUTE} | {
    r for r, a in ALIAS_AGENTS.items() if isinstance(a, CompleteAgent)
}


def _final_agent_graph():
    """Definition graph for the final Buddy version; safe empty fallback."""
    agent = registered_agents.get(FINAL_VERSION_ROUTE)
    if not agent:
        return {"initial_step": None, "steps": []}
    try:
        return agent_graph.build_graph(agent)
    except Exception:  # noqa: BLE001 — viewer is best-effort, never 500
        return {"initial_step": None, "steps": []}


@server.app.get("/api/postprompt/final")
async def postprompt_final(request: Request):
    """Latest captured post-prompt for the final Buddy version (browser-call showcase)."""
    graph = _final_agent_graph()
    calls = [c for c in call_store.STORE.all() if c.get("agent_route") in FINAL_ROUTES]
    if not calls:
        return JSONResponse({"found": False, "call": None, "agent_graph": graph})
    latest = max(calls, key=lambda c: c.get("received_at", 0))
    safe = {k: v for k, v in latest.items() if k != "raw"}
    return JSONResponse({"found": True, "call": safe, "agent_graph": graph})


@server.app.get("/api/account")
async def account_context(request: Request):
    own = _session_creds(request)
    shared = shared_account_active()
    if own:
        mode = "own"
    elif shared:
        mode = "shared"
    else:
        mode = "solo"
    return JSONResponse({
        "mode": mode,
        "shared": shared,
        "has_own": bool(own),
        "space": own.get("SIGNALWIRE_SPACE", "") if own else "",
    })


@server.app.get("/api/agent/graph")
async def api_agent_graph(request: Request):
    """Full contexts/steps definition graph for a registered agent."""
    route = request.query_params.get("route", FINAL_VERSION_ROUTE)
    agent = registered_agents.get(route)
    if not agent:
        return JSONResponse({"found": False, "route": route,
                             "initial_step": None, "steps": []})
    try:
        g = agent_graph.build_graph(agent)
    except Exception:  # noqa: BLE001
        g = {"initial_step": None, "steps": []}
    return JSONResponse({"found": bool(g["steps"]), "route": route, **g})


@server.app.get("/admin/config")
async def admin_get_config(request: Request):
    """Current runtime config (public URL + SWAIG basic auth) for the admin page."""
    return JSONResponse(_CONFIG.snapshot(env_default=_effective_base()))


@server.app.post("/admin/config")
async def admin_set_config(request: Request):
    """Save admin-edited config and apply it live. Empty string clears an override
    (falls back to auto-detected/env); omitted keys are left unchanged."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    _CONFIG.update(
        public_base=body.get("public_base"),
        auth_user=body.get("auth_user"),
        auth_password=body.get("auth_password"),
    )
    _apply_config()
    return JSONResponse(_CONFIG.snapshot(env_default=_effective_base()))


@server.app.get("/admin/swaig")
async def admin_swaig(request: Request):
    """List every registered SWAIG function with its latest health status."""
    return JSONResponse({"functions": function_health.STORE.all()})


@server.app.post("/admin/swaig/test")
async def admin_swaig_test(request: Request):
    """Run one SWAIG function's test case off the event loop and return a verdict."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    name = (body or {}).get("function")
    if not name:
        return JSONResponse({"error": "function name required"}, status_code=400)
    verdict = await asyncio.to_thread(run_swaig_case, name, (body or {}).get("route"))
    return JSONResponse(verdict)


@server.app.get("/admin/errors")
async def admin_errors(request: Request):
    return JSONResponse({"errors": error_store.STORE.all()})


@server.app.delete("/admin/errors")
async def admin_clear_errors(request: Request):
    error_store.STORE.clear()
    return JSONResponse({"status": "cleared"})


@server.app.get("/admin/stream")
async def admin_stream(request: Request):
    """SSE driven by polling the stores' version counters (sync/thread safe)."""
    async def gen():
        last_calls = -1
        last_sessions = -1
        last_swaig = -1
        last_errors = -1
        # Prime the client with current state immediately.
        while True:
            if await request.is_disconnected():
                return
            cv = call_store.STORE.version
            sv = _SESSIONS.version
            fv = function_health.STORE.version
            ev = error_store.STORE.version
            if cv != last_calls:
                last_calls = cv
                payload = _json.dumps({"calls": call_store.STORE.all()})
                yield f"event: calls\ndata: {payload}\n\n"
            if sv != last_sessions:
                last_sessions = sv
                payload = _json.dumps({"sessions": _SESSIONS.admin_snapshot()})
                yield f"event: sessions\ndata: {payload}\n\n"
            if fv != last_swaig:
                last_swaig = fv
                payload = _json.dumps({"functions": function_health.STORE.all()})
                yield f"event: swaig\ndata: {payload}\n\n"
            if ev != last_errors:
                last_errors = ev
                payload = _json.dumps({"errors": error_store.STORE.all()})
                yield f"event: errors\ndata: {payload}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Live Wire — public SSE feed for the browser-call Live Wire panel
# ---------------------------------------------------------------------------

@server.app.get("/api/live-events")
async def live_events_stream(request: Request):
    """Per-session SSE feed for the Live Wire panel (browser-call section).

    SECURITY: unauthenticated endpoint, so events are reduced to server-built
    summary fields only AND scoped to the requesting browser's session. An
    attendee sees only their own call; the presenter's demo no longer leaks
    into everyone's panel. Events with no resolvable session are not streamed.
    """
    import live_events as _le

    sid = getattr(getattr(request, "state", None), "session_id", None)

    def _public(e):
        return {k: e[k] for k in ("seq", "ts", "source", "type", "summary")}

    async def gen():
        # replay a short per-session tail so a freshly-opened panel has context,
        # and advance the cursor past everything already buffered (race-free)
        replay, last = _le.BUS.drain(0, session_id=sid)
        for e in replay[-20:]:
            yield f"event: live\ndata: {_json.dumps([_public(e)])}\n\n"
        while True:
            if await request.is_disconnected():
                return
            evs, last = _le.BUS.drain(last, session_id=sid)
            if evs:
                yield f"event: live\ndata: {_json.dumps([_public(e) for e in evs])}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Source viewer - lets the landing page link to /source/agents/step04_hello.py
# ---------------------------------------------------------------------------

ALLOWED_SOURCE_DIR = os.path.join(os.path.dirname(__file__), "agents")

@server.app.get("/source/{file_path:path}")
async def view_source(file_path: str):
    """Serve agent source files as plain text for easy reading."""
    full = os.path.normpath(os.path.join(os.path.dirname(__file__), file_path))
    # Only serve files inside the agents/ directory
    if not full.startswith(os.path.normpath(ALLOWED_SOURCE_DIR)):
        return PlainTextResponse("Forbidden", status_code=403)
    if not os.path.isfile(full):
        return PlainTextResponse("Not found", status_code=404)
    with open(full) as f:
        return PlainTextResponse(f.read())

# ---------------------------------------------------------------------------
# Landing page - serve static files from web/
# ---------------------------------------------------------------------------
# WHY conditional: web/ does not exist until Task 8 lands; this keeps main.py
# runnable in interim states without 500ing on missing assets.
import os.path
if os.path.isdir("web"):
    server.app.mount("/static", StaticFiles(directory="web"), name="static")

    @server.app.middleware("http")
    async def _no_cache_static(request: Request, call_next):
        # Force fresh static assets so a redeploy never serves a returning
        # attendee a stale cached bundle. "no-cache" still allows conditional
        # revalidation (304s), it just forbids using a cached copy blindly.
        response = await call_next(request)
        # No-cache the static bundle AND the HTML documents that load it (/ and
        # /admin). Otherwise a returning attendee gets a stale cached index whose
        # inline JS is out of date (e.g. a pre-fix modal that won't open).
        if request.url.path.startswith("/static/") or request.url.path in ("/", "/admin"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @server.app.get("/")
    async def landing():
        return FileResponse("web/index.html")

    @server.app.get("/admin")
    async def admin_page():
        return FileResponse("web/admin.html")

# ---------------------------------------------------------------------------
# REST + RELAY pillar Run endpoints (steps 12 + 13)
# ---------------------------------------------------------------------------

# In-flight subprocesses keyed by pillar so a new POST cancels the old one.
_INFLIGHT: dict[str, dict] = {}

PILLAR_TO_SCRIPT = {
    "rest": "python/steps/step12_rest_demo.py",
}

# WHY only project/token/space: step 12 now provisions the agent and mints a
# subscriber token; it no longer sends SMS, so SMS_FROM/SMS_TO are gone.
PILLAR_REQUIRED_ENV = {
    "rest": ["SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_TOKEN", "SIGNALWIRE_SPACE"],
}


async def _terminate_inflight(state: dict) -> None:
    # WHY two-stage: give the script a chance to clean up websockets and
    # in-flight API calls before we hard-kill it.
    proc = state.get("proc")
    if proc and proc.returncode is None:
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    queue: asyncio.Queue = state["queue"]
    await queue.put({"event": "cancelled", "data": "previous run cancelled"})
    await queue.put(None)


async def _pump(stream, queue: asyncio.Queue, stream_name: str) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        await queue.put({
            "event": stream_name,
            "data": line.decode("utf-8", errors="replace").rstrip(),
        })


@server.app.get("/run/{pillar}/inputs")
async def run_inputs(pillar: str, request: Request):
    if pillar not in PILLAR_REQUIRED_ENV:
        return JSONResponse({"error": "unknown pillar"}, status_code=404)
    required = PILLAR_REQUIRED_ENV[pillar]
    creds = build_creds_for(request)
    missing = [k for k in required if not creds.get(k)]
    return {"pillar": pillar, "required": required, "missing": missing}


@server.app.post("/run/{pillar}")
async def run_pillar(pillar: str, request: Request):
    if pillar not in PILLAR_TO_SCRIPT:
        return JSONResponse({"error": "unknown pillar"}, status_code=404)
    raw = await request.body()
    body = json.loads(raw) if raw else {}
    inputs = body.get("inputs", {}) if isinstance(body, dict) else {}

    if pillar in _INFLIGHT:
        await _terminate_inflight(_INFLIGHT.pop(pillar))

    run_id = uuid.uuid4().hex
    queue: asyncio.Queue = asyncio.Queue()
    creds = build_creds_for(request)
    env = {**os.environ, **creds, **{str(k): str(v) for k, v in inputs.items()}}

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", PILLAR_TO_SCRIPT[pillar],
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def supervise():
        await asyncio.gather(
            _pump(proc.stdout, queue, "stdout"),
            _pump(proc.stderr, queue, "stderr"),
        )
        rc = await proc.wait()
        await queue.put({"event": "exit", "data": str(rc)})
        await queue.put(None)
        # Only drop if this is still the current run; a newer POST may have
        # already taken our slot.
        if _INFLIGHT.get(pillar, {}).get("run_id") == run_id:
            _INFLIGHT.pop(pillar, None)

    asyncio.create_task(supervise())
    _INFLIGHT[pillar] = {"proc": proc, "queue": queue, "run_id": run_id}
    return {"pillar": pillar, "run_id": run_id}


@server.app.get("/run/{pillar}/stream/{run_id}")
async def run_stream(pillar: str, run_id: str):
    state = _INFLIGHT.get(pillar)
    if not state or state["run_id"] != run_id:
        return JSONResponse({"error": "no such run"}, status_code=404)
    queue: asyncio.Queue = state["queue"]

    async def gen():
        while True:
            item = await queue.get()
            if item is None:
                yield "event: end\ndata: done\n\n"
                return
            payload = json.dumps({"event": item["event"], "data": item["data"]})
            yield f"event: {item['event']}\ndata: {payload}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

# ---------------------------------------------------------------------------
# Step 13 RELAY: guest token + agent address for the browser SDK
# ---------------------------------------------------------------------------

@server.app.get("/api/relay/config")
async def relay_config(request: Request):
    from python.steps.step12_rest_demo import (
        agent_address_by_name, agent_address_id, agent_resource_name, ensure_agent_handler, mint_guest_token)
    route = request.query_params.get("route")
    if route is not None and route not in {s["route"] for s in GUIDED_STEPS}:
        return JSONResponse({"error": "unknown route"}, status_code=400)
    creds = build_creds_for(request)
    if not creds:
        return JSONResponse({"error": "missing credentials"}, status_code=400)
    session = _SESSIONS.ensure(request.state.session_id)
    try:
        if route and shared_account_active():
            # Per-version resources already exist in shared mode (provisioned
            # with their own dedicated numbers by provision_guided_agents), so
            # resolve THAT resource's address instead of the legacy single
            # HANDLER_NAME resource ensure_agent_handler manages below.
            name = agent_resource_name(route)
            address_id, destination = await asyncio.to_thread(agent_address_by_name, name, None, creds)
            if not address_id:
                return JSONResponse(
                    {"error": "per-version agent not provisioned yet"}, status_code=503
                )
            token = await asyncio.to_thread(mint_guest_token, address_id, creds)
        else:
            # Browser calls (audio + video) reach the COMPLETE agent (/complete) by
            # default: it has every capability plus the video avatar, so it's the
            # best showcase.
            destination = await asyncio.to_thread(
                ensure_agent_handler, _effective_base(), route or "/complete", None, creds, session, request.state.session_id
            )
            address_id = await asyncio.to_thread(agent_address_id, None, creds)
            token = await asyncio.to_thread(mint_guest_token, address_id, creds)
        _SESSIONS.save()
        return JSONResponse({"token": token, "destination": destination})
    except Exception as e:  # noqa: BLE001
        print(f"[relay/config] FAILED: {e.__class__.__name__}: {e}", flush=True)
        return JSONResponse({"error": str(e)}, status_code=503)

# ---------------------------------------------------------------------------
# Shared credentials: one panel above both pillars posts here. Writing into
# os.environ means BOTH the REST subprocess (it inherits os.environ when spawned
# by /run/rest) and the RELAY endpoint (it reads os.environ) pick up the same
# creds. WHY a server-side store: a workshop fork is single-tenant, so holding
# creds in the process for the session is the simplest way to share them across
# pillars without ever putting the admin token in the browser.
# ---------------------------------------------------------------------------

_CRED_KEYS = ("SIGNALWIRE_PROJECT_ID", "SIGNALWIRE_TOKEN", "SIGNALWIRE_SPACE")

_SESSION_COOKIE = "sw_session"


# --- Admin HTTP Basic auth ------------------------------------------------
# The /admin dashboard exposes every call's transcript, summary, and metadata
# across all attendees, so it must not be world-readable on a shared deploy.
# Username defaults to "admin"; password comes from the ADMIN_PASSWORD secret
# and falls back to the SWML basic-auth password so the route is never open.
_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
# Unset → fall back to the SWML basic-auth password (always protected by default).
# Explicitly set to "" → auth disabled (opt-out for trusted/local/CI use).
# Boot-time snapshots kept for tests/introspection; the RUNTIME check resolves
# per request via _admin_password() so a boot-order quirk (auth_pass empty at
# import) or a live SWML-password change can never freeze the gate open/stale.
_admin_pw_env = os.environ.get("ADMIN_PASSWORD")
_ADMIN_PASSWORD = _admin_pw_env if _admin_pw_env is not None else auth_pass
_ADMIN_AUTH_ENABLED = bool(_ADMIN_PASSWORD)


def _admin_password() -> str:
    """The password the admin gate expects RIGHT NOW (dynamic, never frozen).
    ADMIN_PASSWORD env wins (empty string = explicit opt-out); unset falls back
    to the current effective SWML basic-auth password."""
    pw_env = os.environ.get("ADMIN_PASSWORD")
    if pw_env is not None:
        return pw_env
    return _CONFIG.effective_auth()[1] or ""


def _admin_auth_ok(request: Request) -> bool:
    """Constant-time check of the Authorization: Basic header against admin creds."""
    expected_pw = _admin_password()
    if not expected_pw:
        return True                     # gate explicitly disabled
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    user, _, pw = decoded.partition(":")
    return (secrets.compare_digest(user.encode(), os.environ.get("ADMIN_USER", "admin").encode())
            and secrets.compare_digest(pw.encode(), expected_pw.encode()))


@server.app.middleware("http")
async def _session_cookie(request: Request, call_next):
    # Gate the admin dashboard (page + APIs + SSE) behind HTTP Basic auth.
    # The browser prompts once at /admin and reuses the credentials for the
    # /admin/* fetches and the EventSource stream on the same origin.
    _path = request.url.path
    if _admin_password() and (_path == "/admin" or _path.startswith("/admin/")):
        if not _admin_auth_ok(request):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Workshop Admin"'},
                content="Authentication required.",
            )

    # Auto-detect the public base from the first real (non-local) request so the
    # *.replit.app URL self-populates with no Secret to set. A manual admin
    # override always wins (effective_base checks it first).
    _host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if _host and "localhost" not in _host and not _host.startswith(("127.", "0.0.0.0")):
        _proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        if _CONFIG.set_detected_base(f"{_proto}://{_host}"):
            _apply_config()

    sid = request.cookies.get(_SESSION_COOKIE)
    is_new = not sid or _SESSIONS.get(sid) is None
    if is_new:
        sid = session_store.new_session_id()
    request.state.session_id = sid
    _SESSIONS.ensure(sid)
    _SESSIONS.sweep()
    response = await call_next(request)
    if is_new:
        response.set_cookie(_SESSION_COOKIE, sid, max_age=12 * 60 * 60,
                            httponly=True, samesite="lax", secure=True, path="/")
    return response


def shared_account_active() -> bool:
    """True when this deployment runs on the shared workshop account: the build
    runs on the SignalWire env creds and outbound/verification require the
    attendee's own account.

    This is the DEFAULT whenever the shared creds are present (the workshop
    always defaults to the workshop account). Set WORKSHOP_SHARED_ACCOUNT to a
    falsy value (0/false/no/off) to force the per-attendee "bring your own from
    the start" model instead. With no creds present it is always inactive."""
    if not all(os.environ.get(k) for k in _CRED_KEYS):
        return False
    flag = os.environ.get("WORKSHOP_SHARED_ACCOUNT")
    if flag is None:
        return True  # default on when the workshop creds are available
    return flag.strip().lower() not in ("0", "false", "no", "off", "")


def _env_creds() -> dict:
    return {k: os.environ[k] for k in _CRED_KEYS if os.environ.get(k)}


def _session_creds(request: Request) -> dict:
    """Only the creds the attendee entered this session (never env)."""
    rec = _SESSIONS.ensure(request.state.session_id)
    if all(rec["creds"].get(k) for k in _CRED_KEYS):
        return dict(rec["creds"])
    return {}


def creds_for(request: Request) -> dict:
    """Creds for the build/inbound path: the session's own creds, else the
    shared workspace env creds ONLY in explicit WORKSHOP_SHARED_ACCOUNT mode.
    There is no local/dev auto-login: a fresh session with no creds gets {} so
    the attendee must enter their own credentials. Outbound/verification must
    use own_creds_for(), never this."""
    own = _session_creds(request)
    if own:
        return own
    if shared_account_active():
        env = _env_creds()
        if all(env.get(k) for k in _CRED_KEYS):
            return env
    return {}


def own_creds_for(request: Request) -> dict:
    """Creds for outbound + verification: the attendee's OWN account only.
    In shared mode this never falls back to the shared/env token; off shared
    mode it matches creds_for (solo/local dev uses its own env creds)."""
    if shared_account_active():
        return _session_creds(request)
    return creds_for(request)


def build_creds_for(request: Request) -> dict:
    """Creds for the guided-build surface (browser call, dedicated numbers,
    provisioning, wizard reads, pillar runs). In shared mode this is ALWAYS the
    shared workspace, even after the attendee connects their own account: their
    creds are scoped to outbound/verify only (own_creds_for). Off shared mode
    it matches creds_for."""
    if shared_account_active():
        return _env_creds()
    return creds_for(request)


def _credentials_status_for(creds: dict):
    return {
        "configured": all(creds.get(k) for k in _CRED_KEYS),
        "fields": {
            "SIGNALWIRE_PROJECT_ID": bool(creds.get("SIGNALWIRE_PROJECT_ID")),
            "SIGNALWIRE_TOKEN": bool(creds.get("SIGNALWIRE_TOKEN")),
            "SIGNALWIRE_SPACE": creds.get("SIGNALWIRE_SPACE", ""),
        },
    }


@server.app.get("/api/credentials/status")
async def credentials_status(request: Request):
    return JSONResponse(_credentials_status_for(creds_for(request)))


@server.app.post("/api/credentials")
async def set_credentials(request: Request):
    raw = await request.body()
    body = json.loads(raw) if raw else {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "expected a JSON object"}, status_code=400)
    try:
        incoming, changes = creds_normalize.normalize_creds(
            {k: body[k] for k in _CRED_KEYS if k in body})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    for note in changes:
        print(f"[creds] {note}", flush=True)

    rec = _SESSIONS.ensure(request.state.session_id)
    candidate = dict(rec["creds"])
    for k, value in incoming.items():
        if value:
            candidate[k] = value
        else:
            candidate.pop(k, None)
    rec["creds"] = candidate
    if all(rec["creds"].get(k) for k in _CRED_KEYS):
        _SESSIONS.mark_signed_in(request.state.session_id)
    _SESSIONS.save()
    return JSONResponse(_credentials_status_for(creds_for(request)))


@server.app.post("/api/credentials/clear")
async def clear_credentials(request: Request):
    rec = _SESSIONS.ensure(request.state.session_id)
    rec["creds"] = {}
    _SESSIONS.save()
    return JSONResponse({"ok": True})

# ---------------------------------------------------------------------------
# Workshop setup — automate phone-number + webhook plumbing via REST.
# Endpoints used by the new onboarding wizard and the per-agent
# "Point my phone number here" buttons.
# ---------------------------------------------------------------------------

VALID_AGENT_ROUTES = {r for r, _, _ in STEPS}


def _require_public_base():
    base = _effective_base()
    if not base:
        raise RuntimeError("no public URL detected; open /admin and set the Public URL, or set SWML_PROXY_URL_BASE")
    return base


def _normalize_e164(raw: str):
    """Coerce a user-typed destination into E.164, or return "" if implausible.

    Mirrors the frontend normalizeE164: strips spaces/dashes/parens, handles
    00/011 international prefixes and missing +, and defaults bare 10-digit
    numbers to North America (+1)."""
    if not raw:
        return ""
    s = str(raw).strip()
    had_plus = s.startswith("+")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not had_plus and digits.startswith("011"):
        digits = digits[3:]
    elif not had_plus and digits.startswith("00"):
        digits = digits[2:]
    if not digits:
        return ""
    if had_plus:
        return "+" + digits if 8 <= len(digits) <= 15 else ""
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    if 11 <= len(digits) <= 15:
        return "+" + digits
    return ""


def _normalize_route(route: str) -> str:
    if not route or not route.startswith("/"):
        raise RuntimeError("route must start with /")
    if route not in VALID_AGENT_ROUTES:
        raise RuntimeError(f"unknown agent route: {route}")
    return route


def _missing_creds_response(creds):
    if not creds:
        return JSONResponse({"error": "missing credentials"}, status_code=400)
    return None


def _needs_own_account_response(creds):
    """400 for outbound/verify when the session has no own-account creds."""
    if not creds:
        return JSONResponse(
            {"error": "Connect your own SignalWire account to place calls or verify a number.",
             "needs_own_account": True},
            status_code=400,
        )
    return None


def _shared_setup_locked_response():
    """403 for the number wizard on a shared deployment: attendees must never
    purchase or re-route numbers on the shared workshop token. Their own
    numbers are managed through /api/own/*."""
    if shared_account_active():
        return JSONResponse(
            {"error": "Number setup is disabled on the shared workshop deployment.",
             "shared_mode": True},
            status_code=403,
        )
    return None


@server.app.get("/api/setup/status")
async def setup_status(request: Request):
    from python.provisioning import setup_status as _status
    session = _SESSIONS.ensure(request.state.session_id)
    return JSONResponse(_status(build_creds_for(request), session.get("setup", {}), base_url or ""))


@server.app.get("/api/setup/numbers")
async def setup_numbers(request: Request):
    creds = build_creds_for(request)
    r = _missing_creds_response(creds)
    if r: return r
    from python.provisioning import list_existing_numbers
    try:
        nums = await asyncio.to_thread(list_existing_numbers, creds, 3)
        return JSONResponse({"numbers": nums})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{e.__class__.__name__}: {e}"}, status_code=502)


@server.app.post("/api/setup/search")
async def setup_search(request: Request):
    r = _shared_setup_locked_response()
    if r: return r
    creds = creds_for(request)
    r = _missing_creds_response(creds)
    if r: return r
    raw = await request.body(); body = json.loads(raw) if raw else {}
    area_code = body.get("area_code")
    if area_code and not str(area_code).isdigit():
        return JSONResponse({"error": "area_code must be digits"}, status_code=400)
    from python.provisioning import search_available_with_fallback
    try:
        nums, fell_back = await asyncio.to_thread(
            search_available_with_fallback, creds, str(area_code) if area_code else None, 8)
        return JSONResponse({"numbers": nums, "area_code": area_code or None, "fell_back": fell_back})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{e.__class__.__name__}: {e}"}, status_code=502)


@server.app.post("/api/setup/select")
async def setup_select(request: Request):
    r = _shared_setup_locked_response()
    if r: return r
    creds = creds_for(request)
    r = _missing_creds_response(creds)
    if r: return r
    try:
        public = _require_public_base()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    raw = await request.body(); body = json.loads(raw) if raw else {}
    route = body.get("route", "/hello")
    try:
        route = _normalize_route(route)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    sid = body.get("sid"); phone_to_buy = body.get("phone_number")
    if not sid and not phone_to_buy:
        return JSONResponse({"error": "either sid or phone_number is required"}, status_code=400)
    from python.provisioning import configure_existing, purchase_and_configure
    session = _SESSIONS.ensure(request.state.session_id)
    try:
        if sid:
            result = await asyncio.to_thread(configure_existing, creds, sid, route, public, request.state.session_id)
        else:
            result = await asyncio.to_thread(purchase_and_configure, creds, phone_to_buy, route, public, request.state.session_id)
        trace = result.pop("_trace", [])
        session["setup"] = result; _SESSIONS.save()
        return JSONResponse({"setup": result, "_trace": trace})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{e.__class__.__name__}: {e}"}, status_code=502)


@server.app.post("/api/setup/route")
async def setup_route(request: Request):
    r = _shared_setup_locked_response()
    if r: return r
    creds = creds_for(request)
    r = _missing_creds_response(creds)
    if r: return r
    try:
        public = _require_public_base()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    raw = await request.body(); body = json.loads(raw) if raw else {}
    route = body.get("route")
    try:
        route = _normalize_route(route)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from python.provisioning import repoint_to_route
    session = _SESSIONS.ensure(request.state.session_id)
    try:
        result = await asyncio.to_thread(repoint_to_route, creds, session.get("setup", {}), route, public)
        trace = result.pop("_trace", [])
        session["setup"] = result; _SESSIONS.save()
        return JSONResponse({"setup": result, "_trace": trace})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{e.__class__.__name__}: {e}"}, status_code=502)


@server.app.post("/api/setup/reset")
async def setup_reset(request: Request):
    session = _SESSIONS.ensure(request.state.session_id)
    session["setup"] = {}; _SESSIONS.save()
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Verified caller-ID routes
# ---------------------------------------------------------------------------

@server.app.get("/api/verify/needed")
async def verify_needed(request: Request):
    creds = own_creds_for(request)
    if not creds:
        return JSONResponse({"needed": False, "trial": False, "verified": False})
    to = _normalize_e164(request.query_params.get("to") or "")
    from python.steps.step12_rest_demo import account_is_trial, list_verified_caller_ids
    trial = await asyncio.to_thread(account_is_trial, creds=creds)
    verified = False
    if to:
        for v in await asyncio.to_thread(list_verified_caller_ids, creds=creds):
            if v.get("verified") and v.get("number") == to:
                verified = True
                break
    return JSONResponse({"needed": bool(trial and not verified), "trial": bool(trial), "verified": bool(verified)})


@server.app.get("/api/verify/status")
async def verify_status(request: Request):
    from python.steps.step12_rest_demo import list_verified_caller_ids
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    try:
        nums = await asyncio.to_thread(list_verified_caller_ids, creds=creds)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    slim = [{"id": n.get("id"), "number": n.get("number"), "verified": bool(n.get("verified"))}
            for n in nums]
    return JSONResponse({"has_verified": any(n["verified"] for n in slim), "numbers": slim})


@server.app.post("/api/verify/start")
async def verify_start(request: Request):
    from python.steps.step12_rest_demo import create_verified_caller_id
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    raw = await request.body()
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    number = _normalize_e164((body or {}).get("number", ""))
    if not number:
        return JSONResponse(
            {"error": "That doesn't look like a valid phone number. Use a format like +1 555 123 4567."},
            status_code=400)
    try:
        out = await asyncio.to_thread(create_verified_caller_id, number, name=(body or {}).get("name"), creds=creds)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse({"id": out.get("id"), "verified": bool(out.get("verified"))})


@server.app.post("/api/verify/confirm")
async def verify_confirm(request: Request):
    from python.steps.step12_rest_demo import validate_verified_caller_id
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    raw = await request.body()
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    vid, code = (body or {}).get("id"), (body or {}).get("code")
    if not vid or not code:
        return JSONResponse({"error": "id and code are required"}, status_code=400)
    try:
        out = await asyncio.to_thread(validate_verified_caller_id, vid, code, creds=creds)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse({"verified": bool(out.get("verified"))})


@server.app.post("/api/verify/redial")
async def verify_redial(request: Request):
    from python.steps.step12_rest_demo import redial_verified_caller_id
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    raw = await request.body()
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    vid = (body or {}).get("id")
    if not vid:
        return JSONResponse({"error": "id is required"}, status_code=400)
    try:
        await asyncio.to_thread(redial_verified_caller_id, vid, creds=creds)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    return JSONResponse({"ok": True})


@server.app.post("/api/outbound/call")
async def outbound_call(request: Request):
    from python.steps.step12_rest_demo import place_outbound_call
    creds = own_creds_for(request)
    r = _needs_own_account_response(creds)
    if r: return r
    # Defensive parse (matches the setup/verify routes): an empty or non-JSON
    # body must yield a clean 400, never a 500 from request.json() raising.
    raw = await request.body()
    try:
        body = _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    to = (body or {}).get("to", "").strip()
    if not to:
        return JSONResponse({"error": "to is required"}, status_code=400)
    # Fix common formatting sloppiness and reject anything that isn't a plausible
    # E.164 destination (defense in depth; the UI normalizes too).
    to = _normalize_e164(to)
    if not to:
        return JSONResponse(
            {"error": "That doesn't look like a valid phone number. Use a format like +1 555 123 4567."},
            status_code=400)
    session = _SESSIONS.ensure(request.state.session_id)
    from_number = (session.get("setup", {}) or {}).get("phone_number")
    if not from_number:
        from python.steps.step12_rest_demo import first_number_on_account, list_verified_caller_ids
        from_number = await asyncio.to_thread(first_number_on_account, creds=creds)
        if not from_number:
            verified = [v for v in await asyncio.to_thread(list_verified_caller_ids, creds=creds) if v.get("verified")]
            from_number = verified[0].get("number") if verified else None
    if not from_number:
        return JSONResponse(
            {"error": "No phone number on your account to call from. Buy or import a number first."},
            status_code=400)
    try:
        resp = await asyncio.to_thread(
            place_outbound_call,
            to=to, from_number=from_number, route="/outbound",
            creds=creds, sid=request.state.session_id,
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)
    call_id = resp.get("id") if isinstance(resp, dict) else None
    return JSONResponse({"ok": True, "call_id": call_id})


# ---------------------------------------------------------------------------
# Print SWML URLs to console
# ---------------------------------------------------------------------------

if base_url:
    p = urlparse(base_url)
    print("\n" + "=" * 60)
    print("  SWML URLs - paste any into your SignalWire dashboard")
    print("=" * 60 + "\n")
    for route, _cls, desc in STEPS:
        url = f"{p.scheme}://{auth_user}:{auth_pass}@{p.netloc}{route}"
        print(f"  {desc}")
        print(f"  {url}\n")
    print("=" * 60)
    print(f"\n  Landing page: {base_url}\n")
else:
    print("\nNo public URL - SWML URLs will be available once")
    print("REPLIT_DEV_DOMAIN or SWML_PROXY_URL_BASE is set.\n")

# ---------------------------------------------------------------------------
# Startup validation - catch webhook URL problems before accepting traffic
# ---------------------------------------------------------------------------

if base_url:
    errors = []
    # Legacy alias agents (ALIAS_AGENTS) serve live pre-rename webhooks, so
    # their URLs are validated exactly like the listed agents'.
    _all_serving = {**registered_agents, **ALIAS_AGENTS}
    for route, agent in _all_serving.items():
        swaig_url = agent._build_webhook_url("swaig")
        post_url = agent._build_webhook_url("post_prompt")
        if route not in swaig_url:
            errors.append(f"  {route}: swaig URL missing prefix -> {swaig_url}")
        if route not in post_url:
            errors.append(f"  {route}: post_prompt URL missing prefix -> {post_url}")
    if errors:
        print("\n*** WEBHOOK URL VALIDATION FAILED ***")
        for e in errors:
            print(e)
        print("*** Fix: ensure agent.route is set before server.register() ***\n")
    else:
        print(f"\nWebhook URL validation passed for {len(_all_serving)} agents.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\nStarting server with all agents on port {port}...\n")

    server.run()
