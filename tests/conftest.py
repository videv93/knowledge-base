"""Shared test fixtures for the knowledge-base-pipeline test suite."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Set required environment variables for all tests."""
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "test_knowledge_base")
    monkeypatch.setenv("POSTGRES_USER", "test_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test_password")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def mock_db_connection():
    """Provide a mocked database connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch("src.common.db.psycopg2.connect", return_value=mock_conn):
        yield mock_conn, mock_cursor
