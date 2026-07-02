import importlib
from unittest.mock import MagicMock
from starlette.testclient import TestClient
import main
import python.steps.step12_rest_demo as rest

SESSION_CREDS = {
    "SIGNALWIRE_PROJECT_ID": "attendee-project",
    "SIGNALWIRE_TOKEN": "attendee-token",
    "SIGNALWIRE_SPACE": "attendee.signalwire.com",
}


def _own_client_with_captured_dial(monkeypatch):
    """Own-creds TestClient (shared-deployment mode) with place_outbound_call
    and first_number_on_account faked so /api/outbound/call can be exercised
    end-to-end without hitting the SignalWire REST API."""
    monkeypatch.setenv("SIGNALWIRE_PROJECT_ID", "p")
    monkeypatch.setenv("SIGNALWIRE_TOKEN", "t")
    monkeypatch.setenv("SIGNALWIRE_SPACE", "shared.signalwire.com")
    monkeypatch.setenv("WORKSHOP_SHARED_ACCOUNT", "1")
    m = importlib.reload(main)
    client = TestClient(m.server.app, base_url="https://testserver")
    assert client.post("/api/credentials", json=SESSION_CREDS).status_code == 200
    assert client.get("/api/account").json().get("has_own") is True

    captured = {}

    def fake_dial(**kwargs):
        captured["kwargs"] = kwargs
        return {"id": "call-captured"}

    monkeypatch.setattr(rest, "place_outbound_call", fake_dial)
    monkeypatch.setattr(rest, "first_number_on_account", lambda creds=None: "+13125550999")
    return client, captured


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


def test_place_outbound_call_dials_with_from_to_and_step14_url(monkeypatch):
    monkeypatch.setenv("SWML_PROXY_URL_BASE", "https://demo.example.com")
    client = MagicMock()
    client.calling.dial.return_value = {"id": "call-1"}

    out = rest.place_outbound_call(
        to="+15551112222", from_number="+15553334444",
        route="/outbound", client=client, sid="sess-9")

    assert out == {"id": "call-1"}
    kwargs = client.calling.dial.call_args.kwargs
    assert kwargs["to"] == "+15551112222"
    assert kwargs["from"] == "+15553334444"
    # SWML target points at the /outbound route, carries auth + the session id
    assert "/outbound" in kwargs["url"]
    assert "sid=sess-9" in kwargs["url"]
    assert "@demo.example.com" in kwargs["url"]  # basic auth embedded
    # No voicemail_message given → must NOT have voicemail_message param in URL
    assert "voicemail_message=" not in kwargs["url"]


def test_place_outbound_call_threads_voicemail_message(monkeypatch):
    """voicemail_message rides in the /outbound webhook URL as a query param."""
    monkeypatch.setenv("SWML_PROXY_URL_BASE", "https://demo.example.com")
    client = MagicMock()
    client.calling.dial.return_value = {"id": "call-2"}

    rest.place_outbound_call(
        to="+15551112222", from_number="+15553334444",
        route="/outbound", client=client, sid="sess-vm",
        voicemail_message="Hi this is a test")

    kwargs = client.calling.dial.call_args.kwargs
    url = kwargs["url"]
    assert "/outbound" in url
    # The voicemail message must be url-encoded in the query string
    assert "voicemail_message=" in url
    # urlencode uses + for spaces by default; percent-encoding is also acceptable
    assert "Hi+this+is+a+test" in url or "Hi%20this%20is%20a%20test" in url


def test_outbound_call_route_exists():
    paths = {r.path for r in main.server.app.routes}
    assert "/api/outbound/call" in paths


def test_first_number_on_account_returns_first_e164():
    client = MagicMock()
    client.phone_numbers.list.return_value = {"data": [{"number": "+13125550123"},
                                                        {"number": "+13125550999"}]}
    assert rest.first_number_on_account(client=client) == "+13125550123"


def test_first_number_on_account_none_when_empty():
    client = MagicMock()
    client.phone_numbers.list.return_value = {"data": []}
    assert rest.first_number_on_account(client=client) is None


def test_outbound_ignores_client_voicemail_message(monkeypatch):
    # The UI intentionally sends only {to}; a crafted voicemail_message in the
    # body must not reach the dial URL.
    client, captured = _own_client_with_captured_dial(monkeypatch)
    r = client.post("/api/outbound/call",
                    json={"to": "+13125550123", "voicemail_message": "injected"})
    assert r.status_code == 200
    assert captured["kwargs"].get("voicemail_message") in (None, "")
    _restore(monkeypatch)


def test_outbound_call_dials_with_session_creds_not_env_creds(monkeypatch):
    # The attendee's own session creds (from /api/credentials) must reach
    # place_outbound_call — never the shared deployment's env creds.
    client, captured = _own_client_with_captured_dial(monkeypatch)
    r = client.post("/api/outbound/call", json={"to": "+13125550123"})
    assert r.status_code == 200
    assert captured["kwargs"]["creds"]["SIGNALWIRE_PROJECT_ID"] == "attendee-project"
    _restore(monkeypatch)
