import re
import pathlib
import main
from starlette.testclient import TestClient


def test_step14_route_registered():
    assert "/outbound" in main.registered_agents


def test_archived_routes_still_registered():
    for route in ("/step06", "/step07", "/step09"):
        assert route in main.registered_agents


def test_guided_steps_are_four_in_order():
    routes = [s["route"] for s in main.GUIDED_STEPS]
    assert routes == ["/hello", "/tool", "/skills", "/complete"]
    assert [s["version"] for s in main.GUIDED_STEPS] == [1, 2, 3, 4]


def test_capstone_is_step14():
    assert main.OUTBOUND_CAPSTONE["route"] == "/outbound"


def test_curriculum_endpoint():
    client = TestClient(main.server.app)
    data = client.get("/api/curriculum").json()
    assert len(data["guided"]) == 4
    assert data["capstone"]["route"] == "/outbound"


def test_guided_steps_routes_match_ui_steps_meta():
    """DRIFT GUARD: STEPS_META route: values in index.html must equal main.GUIDED_STEPS routes.

    If either list is edited without updating the other this test fails,
    catching silent drift before it ships.
    """
    index_html = pathlib.Path(__file__).resolve().parent.parent / "web" / "index.html"
    content = index_html.read_text(encoding="utf-8")

    # Extract the STEPS_META block: from 'const STEPS_META' up to the closing '];'
    meta_block_match = re.search(
        r"const\s+STEPS_META\s*=\s*\[(.+?)\];",
        content,
        re.DOTALL,
    )
    assert meta_block_match, "Could not find STEPS_META array in web/index.html"
    meta_block = meta_block_match.group(1)

    # Pull out all route: "/slug" values within that block (guided routes are
    # semantic slugs like /hello, /tool, /skills, /complete).
    ui_routes = re.findall(r'route\s*:\s*"(/[a-z][\w-]*)"', meta_block)
    assert ui_routes, "No route: values found in STEPS_META block"

    server_routes = [s["route"] for s in main.GUIDED_STEPS]
    assert ui_routes == server_routes, (
        f"STEPS_META routes in index.html ({ui_routes}) "
        f"do not match main.GUIDED_STEPS routes ({server_routes}). "
        "Update one to match the other."
    )
