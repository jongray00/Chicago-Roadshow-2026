# tests/test_admin_routes.py
"""End-to-end admin endpoint tests against a real server subprocess.

Mirrors tests/test_routes.py: starts main.py on a test port, talks HTTP.
"""
import json
import os
import subprocess
import sys
import time

import pytest
import requests

_TEST_PORT = int(os.environ.get("TEST_SERVER_PORT", "5098"))
BASE_URL = os.environ.get("TEST_BASE_URL", f"http://127.0.0.1:{_TEST_PORT}")


@pytest.fixture(scope="module", autouse=True)
def _server():
    if "TEST_BASE_URL" in os.environ:
        yield
        return
    # Shared workshop account is the default when .env creds are present; opt out
    # (WORKSHOP_SHARED_ACCOUNT=0) so these per-session isolation tests run in the
    # per-attendee path where env creds never auto-authenticate a session.
    env = {**os.environ, "PORT": str(_TEST_PORT), "PYTHONUNBUFFERED": "1",
           "WORKSHOP_SHARED_ACCOUNT": "0",
           "ADMIN_PASSWORD": ""}  # "" disables the admin auth gate for tests
    proc = subprocess.Popen([sys.executable, "main.py"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(50):
        try:
            requests.get(f"{BASE_URL}/admin/calls", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_calls_starts_empty_then_captures_a_post_prompt():
    requests.delete(f"{BASE_URL}/admin/calls", timeout=5)
    assert requests.get(f"{BASE_URL}/admin/calls", timeout=5).json()["calls"] == []

    payload = {
        "call_id": "e2e-1",
        "post_prompt_data": {"raw": "Talked about the weather."},
        "call_log": [{"role": "user", "content": "weather?"}],
        "caller_id_num": "+15551112222",
    }
    requests.post(f"{BASE_URL}/post_prompt", json=payload, timeout=5)

    calls = requests.get(f"{BASE_URL}/admin/calls", timeout=5).json()["calls"]
    assert len(calls) == 1
    assert calls[0]["call_id"] == "e2e-1"
    assert calls[0]["summary"]["raw"] == "Talked about the weather."
    assert calls[0]["transcript"][0]["content"] == "weather?"


def test_sessions_snapshot_masks_token():
    s = requests.Session()
    s.get(f"{BASE_URL}/admin/calls", timeout=5)   # establishes session cookie
    s.post(f"{BASE_URL}/api/credentials", timeout=5, json={
        "SIGNALWIRE_PROJECT_ID": "PX-e2e",
        "SIGNALWIRE_TOKEN": "PT-do-not-leak-1234",
        "SIGNALWIRE_SPACE": "e2e.signalwire.com",
    })
    body = requests.get(f"{BASE_URL}/admin/sessions", timeout=5).text
    assert "PT-do-not-leak" not in body          # raw token never exposed
    rows = json.loads(body)["sessions"]
    assert any(r["project_id"] == "PX-e2e" and r["signed_in_at"] for r in rows)


def test_admin_page_served():
    r = requests.get(f"{BASE_URL}/admin", timeout=5)
    assert r.status_code == 200
    assert "Post-Prompt" in r.text or "post-prompt" in r.text.lower()
