"""Runtime app configuration, editable from the admin dashboard.

Three values that previously required Replit Secrets are managed here at runtime
instead, so a workshop host can fill them in on the /admin page:

- public_base   : the public URL SignalWire calls back (SWML / SWAIG / post_prompt).
                  Auto-detected from the incoming request host; overridable.
- auth_user     : HTTP basic-auth username embedded in provisioned webhook URLs
- auth_password : ...and validated on inbound SignalWire requests.

Overrides are JSON-persisted (mirrors session_store.py) so edits survive a
restart. `effective_*` merges: manual override -> auto-detected -> env -> default.
"""
import json
import os
import threading

import storage

DEFAULT_AUTH_USER = "workshop"
DEFAULT_AUTH_PASSWORD = "password"


class ConfigStore:
    def __init__(self, path=None):
        self._path = path
        self._backend = storage.resolve(path)
        self._lock = threading.Lock()
        # None means "not overridden" -> fall through to detected/env/default.
        self._data = {
            "public_base": None,     # manual override
            "detected_base": None,   # auto-detected from a real request host
            "auth_user": None,
            "auth_password": None,
        }
        # LAUNCH-time env, captured once. _apply_config exports the effective
        # base back into os.environ for downstream consumers (the SDK and
        # step12 read it directly); if ranking read the LIVE env it would
        # launder a stale override into "explicit operator intent" for the
        # life of the process, surviving even an override clear. Ranking must
        # only ever see what the operator actually launched with.
        self._env_base = os.environ.get("SWML_PROXY_URL_BASE")

    # ----- persistence -----
    def load(self):
        if not self._backend:
            return
        raw = self._backend.read()
        if raw is None:
            return
        try:
            data = json.loads(raw)
        except ValueError as e:
            print(f"[config_store] ignoring unreadable config: {e}", flush=True)
            return
        if isinstance(data, dict):
            with self._lock:
                for k in self._data:
                    if k in data:
                        self._data[k] = data[k]

    def save(self):
        if not self._backend:
            return
        with self._lock:
            snapshot = json.dumps(self._data)
        self._backend.write(snapshot)

    # ----- auto-detection -----
    def set_detected_base(self, base):
        """Record the public base seen on a real request. Returns True if changed.

        Dotless hosts are rejected: a public base must be an FQDN, and the
        hosts that reach here without one (starlette's 'testserver',
        'localhost') would poison the persisted config for later live runs.
        """
        host = (base or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        if "." not in host:
            return False
        # Reject transient Replit dev domains (*.replit.dev / *.worf.replit.dev):
        # they are reachable only while the editor is open, so persisting one as
        # the public base bakes a URL into SWML that 404s every post_prompt /
        # SWAIG callback once it goes offline. The stable *.replit.app deploy URL
        # is pinned in replit_setup.startup() instead.
        if host.endswith(".replit.dev"):
            return False
        with self._lock:
            if not base or self._data.get("detected_base") == base:
                return False
            self._data["detected_base"] = base
        self.save()
        return True

    # ----- overrides -----
    def update(self, public_base=None, auth_user=None, auth_password=None):
        """Set manual overrides. Pass a value to set it; pass "" to clear the
        override (fall back to detected/env/default); pass None to leave unchanged.
        """
        with self._lock:
            for key, val in (("public_base", public_base),
                             ("auth_user", auth_user),
                             ("auth_password", auth_password)):
                if val is None:
                    continue
                self._data[key] = (val.strip() or None) if isinstance(val, str) else val
        self.save()

    def drop_stale_quick_tunnel(self, env_default=None):
        """Ephemeral-tunnel guard, run at startup. A persisted public_base
        override pointing at a *.trycloudflare.com quick-tunnel from a prior
        session always outlives its tunnel; once the live environment (env var,
        fresh detection, or the platform default) disagrees, the override is
        guaranteed stale and would silently break every webhook URL. Drop it so
        ranking falls through to the live base. Deliberate custom-domain
        overrides are untouched."""
        with self._lock:
            override = self._data.get("public_base")
            detected = self._data.get("detected_base")
        live = self._env_base or detected or env_default
        if (override and "trycloudflare.com" in override
                and live and live != override):
            self.update(public_base="")
            print(f"[config] dropped stale quick-tunnel override {override} "
                  f"(live base: {live})", flush=True)
            return True
        return False

    # ----- effective values -----
    def effective_base(self, env_default=None):
        # Explicit operator intent (admin override, then env var) outranks the
        # auto-detected guess; detection exists for Replit where no env is set.
        with self._lock:
            override = self._data.get("public_base")
            detected = self._data.get("detected_base")
        return override or self._env_base or detected or env_default

    def effective_auth(self):
        with self._lock:
            user = self._data.get("auth_user")
            pw = self._data.get("auth_password")
        user = user or os.environ.get("SWML_BASIC_AUTH_USER") or DEFAULT_AUTH_USER
        pw = pw or os.environ.get("SWML_BASIC_AUTH_PASSWORD") or DEFAULT_AUTH_PASSWORD
        return user, pw

    def snapshot(self, env_default=None):
        """Sanitized view for the admin UI."""
        with self._lock:
            override = self._data.get("public_base")
            detected = self._data.get("detected_base")
        user, pw = self.effective_auth()
        return {
            "public_base": override or self._env_base or detected or env_default or "",
            "public_base_overridden": bool(override),
            "public_base_detected": detected or "",
            "auth_user": user,
            "auth_password": pw,
        }
