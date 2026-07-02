# tests/test_admin_observability.py
"""End-to-end tests for the Phase 3 SWAIG health + error observability surface.

Mirrors tests/test_admin_routes.py: starts main.py on a fresh test port and
talks HTTP. All workshop SWAIG functions run in-process, so tell_joke can be
exercised offline; get_weather hits a live API and is asserted loosely.
"""
import json
import os
import subprocess
import sys
import time

import pytest
import requests

_TEST_PORT = int(os.environ.get("TEST_SERVER_PORT", "5097"))
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


def test_admin_swaig_lists_functions():
    fns = requests.get(f"{BASE_URL}/admin/swaig", timeout=5).json()["functions"]
    names = {f["name"] for f in fns}
    assert "tell_joke" in names
    assert "get_weather" in names
    for f in fns:
        assert f["status"] in {"untested", "ok", "failing"}


def test_run_test_tell_joke_flips_status():
    r = requests.post(f"{BASE_URL}/admin/swaig/test",
                      json={"function": "tell_joke"}, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ok", "result", "latency_ms"}
    assert body["ok"] is True
    assert isinstance(body["latency_ms"], (int, float))

    fns = requests.get(f"{BASE_URL}/admin/swaig", timeout=5).json()["functions"]
    joke = next(f for f in fns if f["name"] == "tell_joke")
    assert joke["status"] in {"ok", "failing"}
    assert joke["status"] == "ok"


def test_run_test_get_weather_returns_verdict():
    # Hits a live weather API; network failure must not fail the suite, so we
    # only assert the runner returns a well-formed verdict dict.
    r = requests.post(f"{BASE_URL}/admin/swaig/test",
                      json={"function": "get_weather"}, timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ok", "result", "latency_ms"}
    assert isinstance(body["ok"], bool)


def test_run_test_requires_function_name():
    r = requests.post(f"{BASE_URL}/admin/swaig/test", json={}, timeout=5)
    assert r.status_code == 400


def test_unknown_swaig_function_records_error():
    requests.delete(f"{BASE_URL}/admin/errors", timeout=5)
    r = requests.post(f"{BASE_URL}/swaig",
                      json={"function": "does_not_exist", "argument": {}}, timeout=5)
    assert r.status_code == 404
    errors = requests.get(f"{BASE_URL}/admin/errors", timeout=5).json()["errors"]
    assert any("does_not_exist" in (e.get("message") or "") for e in errors)


def test_clear_errors():
    requests.post(f"{BASE_URL}/swaig",
                  json={"function": "still_missing"}, timeout=5)
    assert requests.get(f"{BASE_URL}/admin/errors", timeout=5).json()["errors"]
    requests.delete(f"{BASE_URL}/admin/errors", timeout=5)
    assert requests.get(f"{BASE_URL}/admin/errors", timeout=5).json()["errors"] == []


def test_swaig_result_failed_classifier():
    # Pure unit test — `import main` must not boot the server.
    import main
    assert main._swaig_result_failed({"response": "Here's a joke"}) is False
    assert main._swaig_result_failed({"error": "boom"}) is True
    assert main._swaig_result_failed(
        {"response": "Error executing function 'x': boom"}) is True
    assert main._swaig_result_failed(
        {"response": "Function 'x' not found"}) is True
    assert main._swaig_result_failed("not a dict") is False


def test_admin_swaig_test_unknown_function_no_phantom():
    requests.delete(f"{BASE_URL}/admin/errors", timeout=5)
    r = requests.post(f"{BASE_URL}/admin/swaig/test",
                      json={"function": "definitely_not_real"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["ok"] is False

    # No phantom entry should have been added to the function list.
    fns = requests.get(f"{BASE_URL}/admin/swaig", timeout=5).json()["functions"]
    names = {f["name"] for f in fns}
    assert "definitely_not_real" not in names

    # The error should be recorded.
    errors = requests.get(f"{BASE_URL}/admin/errors", timeout=5).json()["errors"]
    assert any("definitely_not_real" in (e.get("message") or "") for e in errors)


def test_stream_emits_swaig_and_errors_events():
    with requests.get(f"{BASE_URL}/admin/stream", stream=True, timeout=10) as r:
        chunks = b""
        start = time.time()
        for chunk in r.iter_content(chunk_size=512):
            chunks += chunk
            if (b"event: swaig" in chunks and b"event: errors" in chunks) or \
               time.time() - start > 6:
                break
    text = chunks.decode("utf-8", errors="replace")
    assert "event: swaig" in text
    assert "event: errors" in text


def test_admin_html_has_swaig_and_errors_panels():
    """Static-content guard: the admin UI ships the SWAIG + Errors observability
    surface (top-level tabs, panes, SSE listeners, and render functions)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "web", "admin.html"), encoding="utf-8") as f:
        html = f.read()
    for needle in (
        'data-tab="swaig"',
        'data-tab="errors"',
        'id="pane-swaig"',
        'id="pane-errors"',
        'es.addEventListener("swaig"',
        'es.addEventListener("errors"',
        "function renderSwaig",
        "function renderErrors",
    ):
        assert needle in html, f"admin.html missing: {needle}"


def test_admin_swaig_grid_groups_by_name_with_test_all():
    """Static-content guard: the SWAIG pane dedupes cards to one per function
    name (per-route status rows inside each card) and ships a Test All sweep
    button plus a live passing-summary chip."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "web", "admin.html"), encoding="utf-8") as f:
        html = f.read()
    for needle in (
        "function groupSwaigByName",
        "swaig-route-row",
        'id="swaig-testall"',
        'id="swaig-summary"',
        "function runAllSwaig",
        # card-run progress must survive SSE grid re-renders (state keyed by
        # name and re-applied each render, not held on a detached button node)
        "swaigGroupRunning",
        "function syncSwaigGroupBtn",
    ):
        assert needle in html, f"admin.html missing: {needle}"


def test_preflight_cli_offline_runs_and_reports():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "scripts/swaig_preflight.py", "--offline-only"],
        capture_output=True, text=True, timeout=90, cwd=here,
    )
    out = proc.stdout
    assert "tell_joke" in out
    assert "PASS" in out or "FAIL" in out
    assert "passed" in out
