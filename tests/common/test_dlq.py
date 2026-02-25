"""Tests for src.common.dlq module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def test_route_to_dlq_inserts_record():
    """route_to_dlq inserts a record into dead_letter_posts."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import route_to_dlq

        route_to_dlq("https://example.com/post", "ingestion", "Connection timeout")

    mock_cursor.execute.assert_called_once()
    call_args = mock_cursor.execute.call_args
    assert "INSERT INTO dead_letter_posts" in call_args[0][0]
    assert call_args[0][1][0] == "https://example.com/post"
    assert call_args[0][1][1] == "ingestion"
    assert call_args[0][1][2] == "Connection timeout"


def test_list_failures_returns_entries():
    """list_failures returns DeadLetterEntry objects from query results."""
    now = datetime.now(timezone.utc)
    mock_rows = [
        (1, "https://example.com/post1", "ingestion", "Timeout", 0, now, None),
        (2, "https://example.com/post2", "summarization", "API error", 1, now, now),
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = mock_rows
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        entries = list_failures()

    assert len(entries) == 2
    assert entries[0].post_reference == "https://example.com/post1"
    assert entries[0].failure_stage == "ingestion"
    assert entries[1].retry_count == 1


def test_list_failures_filters_by_stage():
    """list_failures filters by failure_stage when provided."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        list_failures(failure_stage="ingestion")

    call_args = mock_cursor.execute.call_args
    assert "WHERE failure_stage = %s" in call_args[0][0]
    assert call_args[0][1] == ("ingestion",)
