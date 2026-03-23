"""Tests for src.common.dlq module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_conn(rows=None, fetchone_row=None):
    """Build a mock connection/cursor pair."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows or []
    mock_cursor.fetchone.return_value = fetchone_row
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def _entry_row(
    id=1,
    post_reference="42",
    failure_stage="summarization",
    failure_reason="API error",
    retry_count=1,
    created_at=None,
    last_retry_at=None,
    resolved=False,
):
    return (
        id,
        post_reference,
        failure_stage,
        failure_reason,
        retry_count,
        created_at or datetime(2026, 3, 1, tzinfo=timezone.utc),
        last_retry_at,
        resolved,
    )


# ---------------------------------------------------------------------------
# route_to_dlq
# ---------------------------------------------------------------------------

def test_route_to_dlq_inserts_record():
    """route_to_dlq inserts a record into dead_letter_posts."""
    mock_conn, mock_cursor = _make_mock_conn()

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import route_to_dlq

        route_to_dlq("https://example.com/post", "ingestion", "Connection timeout")

    mock_cursor.execute.assert_called_once()
    call_args = mock_cursor.execute.call_args
    assert "INSERT INTO dead_letter_posts" in call_args[0][0]
    assert call_args[0][1][0] == "https://example.com/post"
    assert call_args[0][1][1] == "ingestion"
    assert call_args[0][1][2] == "Connection timeout"


# ---------------------------------------------------------------------------
# list_failures
# ---------------------------------------------------------------------------

def test_list_failures_returns_entries():
    """list_failures returns DeadLetterEntry objects from query results."""
    now = datetime.now(timezone.utc)
    mock_rows = [
        (1, "https://example.com/post1", "ingestion", "Timeout", 0, now, None, False),
        (2, "https://example.com/post2", "summarization", "API error", 1, now, now, False),
    ]
    mock_conn, mock_cursor = _make_mock_conn(rows=mock_rows)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        entries = list_failures()

    assert len(entries) == 2
    assert entries[0].post_reference == "https://example.com/post1"
    assert entries[0].failure_stage == "ingestion"
    assert entries[1].retry_count == 1


def test_list_failures_returns_empty_list_when_no_entries():
    """Empty DLQ returns [] without errors — AC #4."""
    mock_conn, _ = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        result = list_failures()

    assert result == []


def test_list_failures_filters_by_stage():
    """list_failures uses WHERE failure_stage = %s when provided."""
    mock_conn, mock_cursor = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        list_failures(failure_stage="ingestion")

    call_args = mock_cursor.execute.call_args
    assert "WHERE failure_stage = %s" in call_args[0][0]
    assert call_args[0][1][0] == "ingestion"


def test_list_failures_orders_by_created_at_desc():
    """list_failures SQL includes ORDER BY created_at DESC."""
    mock_conn, mock_cursor = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        list_failures()

    sql = mock_cursor.execute.call_args[0][0]
    assert "ORDER BY created_at DESC" in sql


def test_list_failures_excludes_resolved_by_default():
    """list_failures default query includes resolved = FALSE filter."""
    mock_conn, mock_cursor = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        list_failures()

    sql = mock_cursor.execute.call_args[0][0]
    assert "resolved = FALSE" in sql


def test_list_failures_includes_resolved_when_flag_set():
    """list_failures passes include_resolved=True through to query params."""
    mock_conn, mock_cursor = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import list_failures

        list_failures(include_resolved=True)

    params = mock_cursor.execute.call_args[0][1]
    # include_resolved=True is passed as last param to allow OR %s = TRUE
    assert True in params


# ---------------------------------------------------------------------------
# reprocess_entry
# ---------------------------------------------------------------------------

def test_reprocess_entry_raises_on_unknown_entry_id():
    """reprocess_entry raises ValueError when entry_id not found."""
    mock_conn, mock_cursor = _make_mock_conn(fetchone_row=None)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import reprocess_entry

        with pytest.raises(ValueError, match="not found"):
            reprocess_entry(9999)


def test_reprocess_entry_raises_on_unknown_stage():
    """reprocess_entry raises ValueError for unknown failure_stage."""
    row = _entry_row(failure_stage="unknown_stage")
    mock_conn, mock_cursor = _make_mock_conn(fetchone_row=row)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import reprocess_entry

        with pytest.raises(ValueError, match="Unknown failure_stage"):
            reprocess_entry(1)


def test_reprocess_entry_marks_resolved_on_success():
    """reprocess_entry updates resolved=TRUE when dispatch succeeds."""
    row = _entry_row(stage="summarization", post_reference="99")
    # Use separate mock_conn instances for _load_entry and the success UPDATE
    mock_conn, mock_cursor = _make_mock_conn(fetchone_row=row)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        with patch("src.summarization.summary_processor.process_single_post"):
            from src.common.dlq import reprocess_entry

            reprocess_entry(1)

    # Check that an UPDATE with resolved = TRUE was issued
    sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any("resolved = TRUE" in s for s in sql_calls)


def test_reprocess_entry_increments_retry_count_on_success():
    """reprocess_entry increments retry_count on successful reprocessing."""
    row = _entry_row(failure_stage="summarization", post_reference="10")
    mock_conn, mock_cursor = _make_mock_conn(fetchone_row=row)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        with patch("src.summarization.summary_processor.process_single_post"):
            from src.common.dlq import reprocess_entry

            reprocess_entry(1)

    sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any("retry_count + 1" in s for s in sql_calls)


def test_reprocess_entry_increments_retry_count_on_failure():
    """reprocess_entry increments retry_count even when dispatch fails."""
    row = _entry_row(failure_stage="summarization", post_reference="10")
    mock_conn, mock_cursor = _make_mock_conn(fetchone_row=row)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        with patch(
            "src.summarization.summary_processor.process_single_post",
            side_effect=RuntimeError("Claude timeout"),
        ):
            from src.common.dlq import reprocess_entry

            with pytest.raises(RuntimeError, match="Claude timeout"):
                reprocess_entry(1)

    sql_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    assert any("retry_count + 1" in s for s in sql_calls)


# ---------------------------------------------------------------------------
# reprocess_by_stage
# ---------------------------------------------------------------------------

def test_reprocess_by_stage_returns_correct_counts():
    """reprocess_by_stage returns attempted/succeeded/failed counts."""
    rows = [
        _entry_row(id=1, failure_stage="ingestion", post_reference="https://a.com/1"),
        _entry_row(id=2, failure_stage="ingestion", post_reference="https://a.com/2"),
    ]
    mock_conn, mock_cursor = _make_mock_conn(rows=rows)

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        with patch("src.common.dlq.reprocess_entry") as mock_reprocess:
            from src.common.dlq import reprocess_by_stage

            result = reprocess_by_stage("ingestion")

    assert result["attempted"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert mock_reprocess.call_count == 2


def test_reprocess_by_stage_returns_zeros_when_no_entries():
    """reprocess_by_stage returns all-zeros when no unresolved entries found."""
    mock_conn, _ = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import reprocess_by_stage

        result = reprocess_by_stage("generation")

    assert result == {"attempted": 0, "succeeded": 0, "failed": 0}


def test_reprocess_by_stage_continues_on_per_entry_failure():
    """reprocess_by_stage does not abort batch when one entry fails."""
    rows = [
        _entry_row(id=1, failure_stage="summarization"),
        _entry_row(id=2, failure_stage="summarization"),
        _entry_row(id=3, failure_stage="summarization"),
    ]
    mock_conn, _ = _make_mock_conn(rows=rows)

    def reprocess_side_effect(entry_id):
        if entry_id == 2:
            raise RuntimeError("transient error")

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        with patch("src.common.dlq.reprocess_entry", side_effect=reprocess_side_effect):
            from src.common.dlq import reprocess_by_stage

            result = reprocess_by_stage("summarization")

    assert result["attempted"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1


# ---------------------------------------------------------------------------
# get_dlq_summary
# ---------------------------------------------------------------------------

def test_get_dlq_summary_returns_correct_counts():
    """get_dlq_summary returns counts grouped by stage from DB rows."""
    mock_conn, mock_cursor = _make_mock_conn(rows=[("ingestion", 3), ("summarization", 2)])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import get_dlq_summary

        result = get_dlq_summary()

    assert result["total_unresolved"] == 5
    assert result["by_stage"]["ingestion"] == 3
    assert result["by_stage"]["summarization"] == 2


def test_get_dlq_summary_returns_zeros_when_empty():
    """get_dlq_summary returns zero total and empty by_stage when DLQ is empty."""
    mock_conn, _ = _make_mock_conn(rows=[])

    with patch("src.common.dlq.get_connection", return_value=mock_conn):
        from src.common.dlq import get_dlq_summary

        result = get_dlq_summary()

    assert result["total_unresolved"] == 0
    assert result["by_stage"] == {}
