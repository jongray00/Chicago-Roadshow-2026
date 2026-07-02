"""Per-version dedicated numbers: each guided version gets its own SWML
resource and its own phone number, so attendees never clobber one another."""
from unittest.mock import MagicMock
import python.steps.step12_rest_demo as rest


def _num(e164, rid=None, url=None, nid=None):
    return {"number": e164, "id": nid or e164, "calling_handler_resource_id": rid,
            "call_relay_script_url": url}


def test_number_is_free_true_when_unrouted():
    assert rest.number_is_free(_num("+15204363368")) is True


def test_number_is_free_false_when_routed_to_resource():
    assert rest.number_is_free(_num("+15204363368", rid="res-1")) is False


def test_number_is_free_false_when_script_url_present():
    assert rest.number_is_free(_num("+1", url="https://x/step10")) is False


def test_agent_resource_name_is_per_route():
    assert rest.agent_resource_name("/hello").endswith(" - hello")
    assert rest.agent_resource_name("/complete").endswith(" - complete")
    assert rest.agent_resource_name("/hello") != rest.agent_resource_name("/tool")


def _client_with(free_numbers, existing_resources=None):
    """Build a mock client. existing_resources: {name: resource_id}."""
    client = MagicMock()
    existing = existing_resources or {}

    def _list_webhooks():
        return {"data": [{"id": rid, "name": nm, "swml_webhook": {}}
                         for nm, rid in existing.items()]}
    client.fabric.swml_webhooks.list.side_effect = _list_webhooks

    created = {"n": 0}
    def _create(name, **kw):
        created["n"] += 1
        rid = f"newres-{created['n']}"
        existing[name] = rid
        return {"id": rid}
    client.fabric.swml_webhooks.create.side_effect = _create

    # phone_numbers.list returns the free pool; routed ones carry their rid.
    routed = {}  # number -> resource_id (populated by assign)
    def _list_numbers(**kw):
        data = []
        for e in free_numbers:
            data.append(_num(e, rid=routed.get(e)))
        return {"data": data}
    client.phone_numbers.list.side_effect = _list_numbers

    def _assign(resource_id, phone_route_id=None, handler=None):
        routed[phone_route_id] = resource_id
        return {}
    client.fabric.resources.assign_phone_route.side_effect = _assign
    return client


def test_provision_assigns_a_distinct_number_per_version():
    pool = ["+15204363368", "+15204363380", "+15204363383", "+15204363397", "+15204363401"]
    client = _client_with(pool)
    mapping = rest.provision_guided_agents(public_base="https://x.test", client=client)
    assert [m["version"] for m in mapping] == [1, 2, 3, 4]
    e164s = [m["e164"] for m in mapping]
    assert len(set(e164s)) == 4, f"numbers must be distinct: {e164s}"
    assert all(e164s), "every version must get a number"
    # Each got a friendly name set.
    assert client.phone_numbers.update.call_count == 4


def test_provision_raises_when_not_enough_free_numbers():
    client = _client_with(["+15204363368", "+15204363380"])  # only 2 free
    try:
        rest.provision_guided_agents(public_base="https://x.test", client=client)
        assert False, "expected RuntimeError for insufficient free numbers"
    except RuntimeError as e:
        assert "free phone numbers" in str(e)


def test_provision_is_idempotent_reuses_existing_assignment():
    # First run assigns; second run must reuse the same numbers, assign nothing new.
    pool = ["+15204363368", "+15204363380", "+15204363383", "+15204363397"]
    client = _client_with(pool)
    first = rest.provision_guided_agents(public_base="https://x.test", client=client)
    assign_calls_after_first = client.fabric.resources.assign_phone_route.call_count
    second = rest.provision_guided_agents(public_base="https://x.test", client=client)
    assert [m["e164"] for m in first] == [m["e164"] for m in second]
    # No new assignments on the second run.
    assert client.fabric.resources.assign_phone_route.call_count == assign_calls_after_first


def test_guided_number_map_reports_unprovisioned_as_none():
    client = _client_with(["+15204363368"])  # no resources exist yet
    mapping = rest.guided_number_map(client=client)
    assert [m["version"] for m in mapping] == [1, 2, 3, 4]
    assert all(m["e164"] is None for m in mapping)


def test_list_account_numbers_slims_to_e164_and_name():
    client = MagicMock()
    client.phone_numbers.list.return_value = {"data": [
        {"number": "+15204363368", "name": "Buddy V1 - Hello"},
        {"number": "+15204363380", "name": None},
        {"name": "no-number-skipped"},  # missing number -> dropped
    ]}
    out = rest.list_account_numbers(client=client)
    assert out == [
        {"e164": "+15204363368", "name": "Buddy V1 - Hello"},
        {"e164": "+15204363380", "name": ""},
    ]
