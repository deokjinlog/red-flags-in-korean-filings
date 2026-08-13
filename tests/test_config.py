import os
from dartweave.config import Settings


def test_defaults_when_env_absent(monkeypatch):
    for key in ("DART_API_KEY", "PG_PORT", "NEO4J_BOLT_PORT", "DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    s = Settings.from_env()
    assert s.pg_port == 5435
    assert s.neo4j_bolt_port == 7687
    assert s.dart_api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "k" * 40)
    monkeypatch.setenv("PG_PORT", "6000")
    s = Settings.from_env()
    assert s.dart_api_key == "k" * 40
    assert s.pg_port == 6000


def test_require_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    s = Settings.from_env()
    try:
        s.require_api_key()
    except RuntimeError as e:
        assert "DART_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
