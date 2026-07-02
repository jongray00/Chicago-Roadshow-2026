# tests/test_shared_account.py
import importlib
import main


def _reload_with_env(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return importlib.reload(main)


def _restore(monkeypatch):
    monkeypatch.undo()
    importlib.reload(main)


class _Req:
    """Minimal stand-in with a fresh session id."""
    def __init__(self, sid="sess-test-1"):
        self.state = type("S", (), {"session_id": sid})()


def test_shared_active_by_default_when_creds_present(monkeypatch):
    # Workshop/shared account is the DEFAULT: creds present + no flag -> active.
    m = _reload_with_env(monkeypatch,
                         SIGNALWIRE_PROJECT_ID="p", SIGNALWIRE_TOKEN="t",
                         SIGNALWIRE_SPACE="s.signalwire.com",
                         WORKSHOP_SHARED_ACCOUNT=None)
    assert m.shared_account_active() is True
    _restore(monkeypatch)


def test_shared_optout_with_flag_zero(monkeypatch):
    # Explicit opt-out forces per-attendee mode even with creds present.
    for val in ("0", "false", "no", "off"):
        m = _reload_with_env(monkeypatch,
                             SIGNALWIRE_PROJECT_ID="p", SIGNALWIRE_TOKEN="t",
                             SIGNALWIRE_SPACE="s.signalwire.com",
                             WORKSHOP_SHARED_ACCOUNT=val)
        assert m.shared_account_active() is False, val
    _restore(monkeypatch)


def test_shared_active_with_flag_and_env(monkeypatch):
    m = _reload_with_env(monkeypatch,
                         SIGNALWIRE_PROJECT_ID="p", SIGNALWIRE_TOKEN="t",
                         SIGNALWIRE_SPACE="s.signalwire.com",
                         WORKSHOP_SHARED_ACCOUNT="1")
    assert m.shared_account_active() is True
    _restore(monkeypatch)


def test_shared_inactive_without_env(monkeypatch):
    m = _reload_with_env(monkeypatch,
                         SIGNALWIRE_PROJECT_ID=None, SIGNALWIRE_TOKEN=None,
                         SIGNALWIRE_SPACE=None, WORKSHOP_SHARED_ACCOUNT="1")
    assert m.shared_account_active() is False
    _restore(monkeypatch)


def test_own_creds_empty_in_shared_mode_without_session_creds(monkeypatch):
    m = _reload_with_env(monkeypatch,
                         SIGNALWIRE_PROJECT_ID="p", SIGNALWIRE_TOKEN="t",
                         SIGNALWIRE_SPACE="s.signalwire.com",
                         WORKSHOP_SHARED_ACCOUNT="1")
    # A fresh session has no creds; own_creds_for must NOT fall back to env.
    assert m.own_creds_for(_Req("sess-shared-empty")) == {}
    _restore(monkeypatch)
