# tests/test_pronunciation.py
"""The final agent says "live" constantly ("live demo", "live API") and the
TTS reads it as /lɪv/ ("liv"). A SWML pronounce rule respells it so the
/laɪv/ reading comes out. Word-bounded so "delivery"/"lives" are untouched."""
import json
import sys

sys.path.insert(0, ".")

import main  # noqa: E402  (builds + registers all agents; server.run() is guarded)


def test_step11_pronounces_live_as_lyve():
    swml = json.loads(main.registered_agents["/complete"]._render_swml())
    ai = next(v["ai"] for v in swml["sections"]["main"]
              if isinstance(v, dict) and "ai" in v)
    rules = ai.get("pronounce") or []
    rule = next((r for r in rules if "live" in r.get("replace", "")), None)
    assert rule is not None, f"no 'live' pronounce rule in: {rules}"
    assert rule["replace"] == r"\blive\b"
    assert rule["with"] == "lyve"
    assert rule.get("ignore_case") is True
