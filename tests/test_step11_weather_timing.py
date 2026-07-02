# tests/test_step11_weather_timing.py
"""Regression guard for the greeting-step "narrate then stall" timing bug.

A production call log showed Buddy answer a weather request in the greeting
step by speaking a yielding "let me check the weather, please hold" line and
then waiting. The next_step transition to the weather step and the get_weather
call only fired on the caller's NEXT utterance, leaving ~14 seconds of dead air.

The fix keeps tools scoped per step (so step_change events still power the
State Flow tree) but (a) supplies next_step internal fillers so the platform
speaks DURING the transition instead of leaving the model to narrate a yield,
and (b) instructs the greeting step to move to the chosen topic immediately
without announcing a check, fetch, or hold. The destination step owns the
"checking" audio via the get_weather SWAIG fillers, which play during execution.
"""
import json
import sys

sys.path.insert(0, ".")

import main  # noqa: E402  (builds + registers all agents; server.run() is guarded)


def _step11_ai():
    swml = json.loads(main.registered_agents["/complete"]._render_swml())
    return next(v["ai"] for v in swml["sections"]["main"]
                if isinstance(v, dict) and "ai" in v)


def _step(ai, name):
    steps = ai["prompt"]["contexts"]["default"]["steps"]
    return next(s for s in steps if s["name"] == name)


def test_next_step_internal_fillers_present():
    """During-transition audio must exist so the model is not tempted to fill
    the gap with a yielding narration of its own."""
    ai = _step11_ai()
    internal = ai["SWAIG"].get("internal_fillers") or {}
    phrases = (internal.get("next_step") or {}).get("en-US") or []
    assert phrases, f"no next_step internal fillers in: {internal}"


def test_greeting_forbids_pre_transition_narration():
    """The greeting step must tell the model to move to the chosen topic
    immediately, without announcing a check/fetch/hold before transitioning."""
    text = _step(_step11_ai(), "greeting")["text"].lower()
    assert "without announcing" in text or "do not say you are about to" in text, \
        f"greeting step lacks a no-pre-transition-narration directive: {text}"


def test_greeting_stays_scoped_with_no_functions():
    """Keeping functions='none' in greeting preserves the scoped-tool demo and
    the step_change events that drive the State Flow tree."""
    assert _step(_step11_ai(), "greeting")["functions"] == "none"


def test_weather_step_owns_get_weather_with_execution_fillers():
    """The weather step still scopes get_weather, and get_weather keeps its
    fillers so audio plays DURING the fetch (not before a silent gap)."""
    ai = _step11_ai()
    assert _step(ai, "weather")["functions"] == ["get_weather"]
    gw = next(f for f in ai["SWAIG"]["functions"] if f["function"] == "get_weather")
    assert gw.get("fillers", {}).get("en-US"), f"get_weather lost its fillers: {gw}"
