"""Tests for src/ingestion/content_extractor.py."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from src.common.models import BlogSource


def _make_source(**kwargs):
    defaults = {
        "id": 1,
        "rss_feed_url": "https://testblog.com/feed",
        "name": "Test Blog",
        "category": "Software Engineering",
        "quality_rating": 5,
    }
    defaults.update(kwargs)
    return BlogSource(**defaults)


def _make_entry(**kwargs):
    defaults = {
        "title": "Test Post",
        "body": "Post body content.",
        "url": "https://testblog.com/post-1",
        "publication_date": datetime(2026, 2, 24, 10, 0, 0, tzinfo=timezone.utc),
        "author_name": "Jane Doe",
    }
    defaults.update(kwargs)
    return defaults


class TestIngestPosts:
    """Tests for ingest_posts function."""

    def test_successful_insertion_returns_success_count(self, mock_db_connection):
        from src.ingestion.content_extractor import ingest_posts

        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1  # 1 row inserted

        source = _make_source()
        entries = [_make_entry()]
        metrics = ingest_posts(source, entries)

        assert metrics["success_count"] == 1
        assert metrics["duplicate_count"] == 0
        assert metrics["failure_count"] == 0
        # 3 calls: SAVEPOINT, INSERT, RELEASE SAVEPOINT
        assert mock_cursor.execute.call_count == 3

    def test_duplicate_url_returns_duplicate_count(self, mock_db_connection):
        from src.ingestion.content_extractor import ingest_posts

        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 0  # 0 rows = duplicate skipped

        source = _make_source()
        entries = [_make_entry()]
        metrics = ingest_posts(source, entries)

        assert metrics["success_count"] == 0
        assert metrics["duplicate_count"] == 1
        assert metrics["failure_count"] == 0

    def test_failed_insertion_routes_to_dlq(self, mock_db_connection):
        from src.ingestion.content_extractor import ingest_posts

        mock_conn, mock_cursor = mock_db_connection
        # Use psycopg2.Error to match the specific except clause
        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # SAVEPOINT call succeeds (call 1), INSERT fails (call 2)
            if call_count == 2:
                raise psycopg2.Error("DB error")

        mock_cursor.execute.side_effect = execute_side_effect

        source = _make_source()
        entries = [_make_entry()]

        with patch("src.ingestion.content_extractor.dlq") as mock_dlq:
            metrics = ingest_posts(source, entries)

        assert metrics["failure_count"] == 1
        assert metrics["success_count"] == 0
        mock_dlq.route_to_dlq.assert_called_once()
        args = mock_dlq.route_to_dlq.call_args[0]
        assert args[1] == "ingestion"

    def test_mixed_results_metrics(self, mock_db_connection):
        from src.ingestion.content_extractor import ingest_posts

        mock_conn, mock_cursor = mock_db_connection

        # Savepoint flow per entry: SAVEPOINT, INSERT, RELEASE (3 calls per success/dup)
        # For failure: SAVEPOINT, INSERT (raises), ROLLBACK TO SAVEPOINT (3 calls)
        # Entry 1: SAVEPOINT(1), INSERT(2), RELEASE(3) — success
        # Entry 2: SAVEPOINT(4), INSERT(5), RELEASE(6) — duplicate
        # Entry 3: SAVEPOINT(7), INSERT(8 raises), ROLLBACK(9) — failure
        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 8:  # INSERT for third entry
                raise psycopg2.Error("DB error")

        mock_cursor.execute.side_effect = execute_side_effect
        # rowcount after INSERT: 1 for first entry (call 2), 0 for second (call 5)
        type(mock_cursor).rowcount = property(lambda self: 1 if call_count == 3 else 0)

        source = _make_source()
        entries = [
            _make_entry(url="https://testblog.com/post-1"),
            _make_entry(url="https://testblog.com/post-2"),
            _make_entry(url="https://testblog.com/post-3"),
        ]

        with patch("src.ingestion.content_extractor.dlq"):
            metrics = ingest_posts(source, entries)

        assert metrics["success_count"] == 1
        assert metrics["duplicate_count"] == 1
        assert metrics["failure_count"] == 1

    def test_dlq_failure_does_not_crash_ingestion(self, mock_db_connection):
        """DLQ routing failure should not crash the ingestion loop."""
        from src.ingestion.content_extractor import ingest_posts

        mock_conn, mock_cursor = mock_db_connection
        call_count = 0

        def execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:  # INSERT fails
                raise psycopg2.Error("DB error")

        mock_cursor.execute.side_effect = execute_side_effect

        source = _make_source()
        entries = [_make_entry()]

        with patch("src.ingestion.content_extractor.dlq") as mock_dlq:
            mock_dlq.route_to_dlq.side_effect = Exception("DLQ also broken")
            metrics = ingest_posts(source, entries)

        # Should still record the failure, not crash
        assert metrics["failure_count"] == 1


# ---------------------------------------------------------------------------
# reingest_by_url (Story 6.1)
# ---------------------------------------------------------------------------

def _make_mock_conn(fetchone_row=None):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_row
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def test_reingest_by_url_marks_resolved_when_post_exists():
    """reingest_by_url returns normally when post found — false positive case."""
    mock_conn, _ = _make_mock_conn(fetchone_row=(42,))

    with patch("src.ingestion.content_extractor.get_connection", return_value=mock_conn):
        from src.ingestion.content_extractor import reingest_by_url

        # Should not raise — post exists, ingestion was a false positive
        reingest_by_url("https://example.com/post")


def test_reingest_by_url_raises_lookup_error_when_post_missing():
    """reingest_by_url raises LookupError when post not in raw_blog_posts."""
    mock_conn, _ = _make_mock_conn(fetchone_row=None)

    with patch("src.ingestion.content_extractor.get_connection", return_value=mock_conn):
        from src.ingestion.content_extractor import reingest_by_url

        with pytest.raises(LookupError, match="Post not found in raw_blog_posts"):
            reingest_by_url("https://example.com/missing")
