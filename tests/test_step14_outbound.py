# tests/test_step14_outbound.py
import json
from python.steps.step14_outbound import OutboundAgent


def _render(agent):
    """Return the agent's rendered SWML as a dict."""
    doc = agent._render_swml()  # AgentBase renders to a JSON string
    return json.loads(doc) if isinstance(doc, str) else doc


def _ai_params(swml):
    for section in swml["sections"]["main"]:
        if "ai" in section:
            return section["ai"].get("params", {})
    raise AssertionError("no ai verb in rendered SWML")


def test_outbound_waits_for_user():
    params = _ai_params(_render(OutboundAgent(route="/outbound")))
    assert params.get("wait_for_user") is True


def test_outbound_direction_is_outbound():
    params = _ai_params(_render(OutboundAgent(route="/outbound")))
    assert params.get("direction") == "outbound"


def test_outbound_prompt_mentions_voicemail():
    agent = OutboundAgent(route="/outbound")
    swml = _render(agent)
    blob = json.dumps(swml).lower()
    assert "voicemail" in blob
    # prompt references the global_data template variable
    assert "${global_data.voicemail_message}" in json.dumps(swml)


def test_outbound_records_call():
    swml = _render(OutboundAgent(route="/outbound"))
    blob = json.dumps(swml).lower()
    assert "record_call" in blob


def test_on_swml_request_threads_voicemail_and_sid():
    """Custom voicemail_message and sid both land in global_data."""
    agent = OutboundAgent(route="/outbound")
    result = agent.on_swml_request(
        request_data={"sid": "s1", "voicemail_message": "Custom VM text"}
    )
    assert result is not None
    gd = result["global_data"]
    assert gd["workshop_session_id"] == "s1"
    assert gd["voicemail_message"] == "Custom VM text"


def test_on_swml_request_default_voicemail_when_absent():
    """With no voicemail_message provided, global_data still has a non-None default."""
    agent = OutboundAgent(route="/outbound")
    result = agent.on_swml_request(request_data={"sid": "s2"})
    assert result is not None
    gd = result["global_data"]
    assert gd.get("voicemail_message") is not None
    assert len(gd["voicemail_message"]) > 10  # non-trivial default


def test_bare_inbound_request_gets_default_voicemail():
    # A direct inbound call to /outbound has no sid and no voicemail_message.
    # The agent must still inject the default message so the prompt never
    # renders a literal ${global_data.voicemail_message}.
    from python.steps.step14_outbound import OutboundAgent
    agent = OutboundAgent(route="/outbound")
    out = agent.on_swml_request(request_data={}, callback_path=None, request=None)
    assert out is not None
    assert out["global_data"]["voicemail_message"] == agent._DEFAULT_VOICEMAIL_MESSAGE


def test_rendered_swml_contains_voicemail_template_variable():
    """The literal ${global_data.voicemail_message} appears in rendered SWML."""
    swml = _render(OutboundAgent(route="/outbound"))
    assert "${global_data.voicemail_message}" in json.dumps(swml)
