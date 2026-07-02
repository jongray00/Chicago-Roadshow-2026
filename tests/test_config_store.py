"""Unit tests for the runtime ConfigStore (no server, no network)."""
import config_store


def _fresh(monkeypatch, tmp_path):
    for k in ("SWML_PROXY_URL_BASE", "SWML_BASIC_AUTH_USER", "SWML_BASIC_AUTH_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    return config_store.ConfigStore(path=str(tmp_path / "cfg.json"))


def test_effective_base_precedence(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    # default fallback
    assert c.effective_base(env_default="https://startup") == "https://startup"
    # detected beats startup default (the Replit no-env case)
    c.set_detected_base("https://detected.replit.app")
    assert c.effective_base(env_default="https://startup") == "https://detected.replit.app"
    # explicit env beats the detected guess (operator intent wins; a poisoned
    # detected_base must never override a deliberately-set tunnel URL).
    # LAUNCH-time semantics: the env is captured at construction, so setting
    # it requires a fresh store (a live env mutation mid-process is exactly
    # the laundering vector the capture exists to block).
    monkeypatch.setenv("SWML_PROXY_URL_BASE", "https://env")
    c = config_store.ConfigStore(path=str(tmp_path / "cfg.json")); c.load()
    c.set_detected_base("https://detected.replit.app")
    assert c.effective_base(env_default="https://startup") == "https://env"
    # manual override beats everything
    c.update(public_base="https://override")
    assert c.effective_base(env_default="https://startup") == "https://override"


def test_effective_auth_defaults_then_override(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    assert c.effective_auth() == ("workshop", "password")
    c.update(auth_user="alice", auth_password="s3cret")
    assert c.effective_auth() == ("alice", "s3cret")


def test_empty_string_clears_override(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    c.update(public_base="https://override")
    assert c.effective_base(env_default="https://startup") == "https://override"
    c.update(public_base="")  # clear -> fall back to default
    assert c.effective_base(env_default="https://startup") == "https://startup"


def test_set_detected_base_change_detection(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    assert c.set_detected_base("https://a.replit.app") is True
    assert c.set_detected_base("https://a.replit.app") is False  # unchanged
    assert c.set_detected_base("https://b.replit.app") is True


def test_persistence_round_trip(monkeypatch, tmp_path):
    path = str(tmp_path / "cfg.json")
    c1 = config_store.ConfigStore(path=path)
    c1.update(public_base="https://kept", auth_user="bob")
    c2 = config_store.ConfigStore(path=path)
    c2.load()
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    assert c2.effective_base() == "https://kept"
    assert c2.effective_auth()[0] == "bob"


def test_snapshot_reports_source(monkeypatch, tmp_path):
    c = _fresh(monkeypatch, tmp_path)
    c.set_detected_base("https://detected.replit.app")
    snap = c.snapshot()
    assert snap["public_base"] == "https://detected.replit.app"
    assert snap["public_base_overridden"] is False
    c.update(public_base="https://override")
    assert c.snapshot()["public_base_overridden"] is True


def test_env_outranks_detected_base(tmp_path, monkeypatch):
    # An operator-set SWML_PROXY_URL_BASE is explicit intent; the detected
    # base is a guess (and can be poisoned — in-process test clients report
    # host 'testserver', which once persisted breaks live resource repoints).
    monkeypatch.setenv("SWML_PROXY_URL_BASE", "https://real-tunnel.example.com")
    store = config_store.ConfigStore(path=str(tmp_path / "c.json"))
    store.set_detected_base("https://detected.example.com")
    assert store.effective_base() == "https://real-tunnel.example.com"
    # Admin override still wins over everything.
    store.update(public_base="https://admin.example.com")
    assert store.effective_base() == "https://admin.example.com"


def test_detected_base_rejects_dotless_hosts(tmp_path, monkeypatch):
    # 'testserver' (starlette TestClient), 'localhost' and friends can never
    # be a public URL; recording them poisons .workshop_config.json.
    monkeypatch.delenv("SWML_PROXY_URL_BASE", raising=False)
    store = config_store.ConfigStore(path=str(tmp_path / "c.json"))
    assert store.set_detected_base("http://testserver") is False
    assert store.set_detected_base("https://localhost") is False
    assert store.effective_base(env_default=None) is None
    assert store.set_detected_base("https://abc.trycloudflare.com") is True
