"""Thread-safe, JSON-persisted health state for each SWAIG function.

Records are keyed by (route, name), NOT name alone: the workshop registers the
same function name on several agents (three different tell_joke implementations
live on /step06, /step07, and /complete), and each implementation needs its own
row, label, and test result. `kind` distinguishes how the function is wired:
"tool" (custom define_tool handler), "skill" (registered by an SDK skill, with
the skill name in `skill`), or "datamap" (serverless, runs on SignalWire).

Mirrors call_store.py: a lock-guarded dict + a monotonically increasing
version counter the /admin SSE stream polls, plus best-effort JSON persistence.
"""
import json
import os
import threading
import time

import storage


def _key(route, name):
    return f"{route or ''}:{name}"


class FunctionHealth:
    def __init__(self, path=None):
        self._path = path
        self._backend = storage.resolve(path)
        self._fns = {}  # (route, name) key -> record
        self._lock = threading.Lock()
        self.version = 0

    def register(self, name, route=None, kind="tool", skill=None):
        with self._lock:
            key = _key(route, name)
            rec = self._fns.get(key)
            if rec is None:
                self._fns[key] = {
                    "name": name, "route": route, "kind": kind, "skill": skill,
                    "status": "untested", "last_detail": "", "last_latency_ms": None,
                    "last_run_at": None,
                }
                self.version += 1
            else:
                rec["kind"] = kind or rec["kind"]
                rec["skill"] = skill if skill is not None else rec.get("skill")

    def record_result(self, name, ok, detail="", latency_ms=None, route=None):
        with self._lock:
            key = _key(route, name)
            rec = self._fns.setdefault(key, {
                "name": name, "route": route, "kind": "tool", "skill": None})
            rec["status"] = "ok" if ok else "failing"
            rec["last_detail"] = (detail or "")[:500]
            rec["last_latency_ms"] = latency_ms
            rec["last_run_at"] = time.time()
            self.version += 1
        self.save()

    def all(self):
        with self._lock:
            return [dict(v) for v in self._fns.values()]

    def save(self):
        if not self._backend:
            return
        with self._lock:
            snapshot = json.dumps(list(self._fns.values()))
        self._backend.write(snapshot)

    def load(self):
        if not self._backend:
            return
        raw = self._backend.read()
        if raw is None:
            return
        try:
            data = json.loads(raw)
        except ValueError as e:
            print(f"[function_health] ignoring unreadable data: {e}", flush=True)
            return
        if isinstance(data, list):
            with self._lock:
                # Records without a route predate per-route keying; replaying
                # them would resurrect the old name-collapsed rows.
                self._fns = {
                    _key(r["route"], r["name"]): r
                    for r in data
                    if "name" in r and r.get("route")
                }


STORE = FunctionHealth(path=".workshop_function_health.json")
STORE.load()
