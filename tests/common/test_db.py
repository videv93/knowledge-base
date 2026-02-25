"""Tests for src.common.db module."""

from unittest.mock import MagicMock, patch


def test_get_connection_commits_on_success():
    """get_connection() commits the transaction on successful exit."""
    mock_conn = MagicMock()

    with patch("src.common.db.psycopg2.connect", return_value=mock_conn):
        from src.common.db import get_connection

        with get_connection() as conn:
            pass

    mock_conn.commit.assert_called_once()
    mock_conn.rollback.assert_not_called()
    mock_conn.close.assert_called_once()


def test_get_connection_rolls_back_on_exception():
    """get_connection() rolls back the transaction on exception."""
    mock_conn = MagicMock()

    with patch("src.common.db.psycopg2.connect", return_value=mock_conn):
        from src.common.db import get_connection

        try:
            with get_connection() as conn:
                raise ValueError("test error")
        except ValueError:
            pass

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_conn.close.assert_called_once()
