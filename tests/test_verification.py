from unittest.mock import MagicMock
import python.steps.step12_rest_demo as rest


def _fake_client(verified_list=None):
    client = MagicMock()
    client.verified_callers.list.return_value = {"data": verified_list or []}
    client.verified_callers.create.return_value = {"id": "vid-1", "verified": False}
    client.verified_callers.submit_verification.return_value = {"id": "vid-1", "verified": True}
    client.verified_callers.redial_verification.return_value = {"id": "vid-1"}
    return client


def test_list_returns_data_array():
    client = _fake_client([{"id": "a", "number": "+15551112222", "verified": True}])
    out = rest.list_verified_caller_ids(client=client)
    assert out == [{"id": "a", "number": "+15551112222", "verified": True}]


def test_has_verified_number_true_when_any_verified():
    client = _fake_client([{"id": "a", "verified": False}, {"id": "b", "verified": True}])
    assert rest.has_verified_number(client=client) is True


def test_has_verified_number_false_when_none_verified():
    client = _fake_client([{"id": "a", "verified": False}])
    assert rest.has_verified_number(client=client) is False


def test_create_posts_number_and_name():
    client = _fake_client()
    out = rest.create_verified_caller_id("+15551112222", name="Workshop", client=client)
    client.verified_callers.create.assert_called_once_with(number="+15551112222", name="Workshop")
    assert out["id"] == "vid-1" and out["verified"] is False


def test_validate_submits_code():
    client = _fake_client()
    out = rest.validate_verified_caller_id("vid-1", "123456", client=client)
    client.verified_callers.submit_verification.assert_called_once_with(
        "vid-1", verification_code="123456")
    assert out["verified"] is True


# ---------------------------------------------------------------------------
# Task 4: route-presence tests
# ---------------------------------------------------------------------------
def test_verify_routes_exist():
    import main  # noqa: PLC0415
    paths = {r.path for r in main.server.app.routes}
    assert "/api/verify/status" in paths
    assert "/api/verify/start" in paths
    assert "/api/verify/confirm" in paths
    assert "/api/verify/redial" in paths
