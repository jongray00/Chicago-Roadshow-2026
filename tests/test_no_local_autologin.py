"""Regression guard: local .env creds must NEVER auto-authenticate a session.

Before this guard, `env_fallback_allowed()` let any non-Replit process fall back
to the `SIGNALWIRE_*` env/.env creds, so every fresh browser session was
pre-authenticated (the "auto-login" we removed). Attendees must enter their own
credentials; env creds are used ONLY in explicit WORKSHOP_SHARED_ACCOUNT mode.
"""
import importlib
import main


class _Req:
    def __init__(self, sid="sess-no-autologin"):
        self.state = type("S", (), {"session_id": sid})()


def _reload_with_env(monkeypatch, **env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    return importlib.reload(main)


def test_no_local_env_autologin(monkeypatch):
    # In per-attendee mode (WORKSHOP_SHARED_ACCOUNT=0 opt-out), a fresh session
    # must get nothing back even though env creds are present -> the credential
    # screen, never a silent local .env auto-login. (Shared/workshop mode is now
    # the default; this guards the opt-out path.)
    m = _reload_with_env(
        monkeypatch,
        SIGNALWIRE_PROJECT_ID="env-project",
        SIGNALWIRE_TOKEN="env-token",
        SIGNALWIRE_SPACE="env.signalwire.com",
        WORKSHOP_SHARED_ACCOUNT="0",
        REPLIT_DEPLOYMENT=None,
    )
    assert m.creds_for(_Req()) == {}
    assert m.build_creds_for(_Req()) == {}
    assert m.own_creds_for(_Req()) == {}
    monkeypatch.undo()
    importlib.reload(main)


def test_shared_mode_still_uses_env_creds(monkeypatch):
    # Shared-account mode is preserved: the build path still resolves to the
    # shared workspace env creds when the operator opts in.
    m = _reload_with_env(
        monkeypatch,
        SIGNALWIRE_PROJECT_ID="shared-project",
        SIGNALWIRE_TOKEN="shared-token",
        SIGNALWIRE_SPACE="shared.signalwire.com",
        WORKSHOP_SHARED_ACCOUNT="1",
    )
    assert m.build_creds_for(_Req("sess-shared"))["SIGNALWIRE_PROJECT_ID"] == "shared-project"
    monkeypatch.undo()
    importlib.reload(main)
