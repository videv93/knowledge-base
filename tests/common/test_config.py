"""Tests for src.common.config module."""

import importlib

import pytest


def test_config_loads_required_vars(monkeypatch):
    """Config loads all required Postgres variables successfully."""
    monkeypatch.setenv("POSTGRES_HOST", "myhost")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_DB", "mydb")
    monkeypatch.setenv("POSTGRES_USER", "myuser")
    monkeypatch.setenv("POSTGRES_PASSWORD", "mypass")

    import src.common.config as config

    importlib.reload(config)

    assert config.POSTGRES_HOST == "myhost"
    assert config.POSTGRES_PORT == 5433
    assert config.POSTGRES_DB == "mydb"
    assert config.POSTGRES_USER == "myuser"
    assert config.POSTGRES_PASSWORD == "mypass"


def test_config_raises_at_import_on_missing_var(monkeypatch):
    """Config raises RuntimeError at import/reload when required var is missing."""
    monkeypatch.delenv("POSTGRES_HOST", raising=False)

    import src.common.config as config

    with pytest.raises(RuntimeError, match="Missing required environment variables"):
        importlib.reload(config)


def test_config_optional_vars_have_defaults(monkeypatch):
    """Optional config vars default to empty string or sensible defaults."""
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("BEEHIIV_API_KEY", raising=False)

    import src.common.config as config

    importlib.reload(config)

    assert config.CLAUDE_API_KEY == ""
    assert config.BEEHIIV_API_KEY == ""
    assert config.LOG_LEVEL == "DEBUG"  # Set by conftest


def test_config_log_level(monkeypatch):
    """LOG_LEVEL env var is read correctly."""
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    import src.common.config as config

    importlib.reload(config)

    assert config.LOG_LEVEL == "WARNING"
