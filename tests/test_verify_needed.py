from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import python.steps.step12_rest_demo as rest


def _num(created_iso):
    return {"number": "+13120000000", "created_at": created_iso}


def test_account_with_old_number_is_not_trial():
    client = MagicMock()
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    client.phone_numbers.list.return_value = {"data": [_num(old)]}
    assert rest.account_is_trial(client=client) is False


def test_account_with_old_number_z_suffix_is_not_trial():
    # The live Relay API returns created_at with a 'Z' suffix (e.g.
    # "2026-06-24T19:31:10Z"); exercise the Z -> +00:00 normalization path.
    client = MagicMock()
    client.phone_numbers.list.return_value = {"data": [_num("2020-06-24T19:31:10Z")]}
    assert rest.account_is_trial(client=client) is False


def test_account_with_only_today_number_is_trial():
    client = MagicMock()
    today = datetime.now(timezone.utc).isoformat()
    client.phone_numbers.list.return_value = {"data": [_num(today)]}
    assert rest.account_is_trial(client=client) is True


def test_account_with_no_numbers_is_trial():
    client = MagicMock()
    client.phone_numbers.list.return_value = {"data": []}
    assert rest.account_is_trial(client=client) is True


def test_account_is_trial_defensive_on_error():
    client = MagicMock()
    client.phone_numbers.list.side_effect = RuntimeError("boom")
    assert rest.account_is_trial(client=client) is True
