"""Tests for src/ingestion/source_loader.py."""


class TestGetActiveSources:
    """Tests for get_active_sources()."""

    def test_returns_blog_source_list(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, "https://blog.example.com/rss", "Example Blog", "Software Engineering", 8, "active", None, None, None),
        ]

        from src.ingestion.source_loader import get_active_sources

        sources = get_active_sources()

        assert len(sources) == 1
        assert sources[0].name == "Example Blog"
        assert sources[0].rss_feed_url == "https://blog.example.com/rss"
        assert sources[0].category == "Software Engineering"
        assert sources[0].quality_rating == 8
        assert sources[0].status == "active"

    def test_filters_by_active_status(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.ingestion.source_loader import get_active_sources

        get_active_sources()

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE status = 'active'" in executed_sql

    def test_returns_empty_list_when_no_active_sources(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.ingestion.source_loader import get_active_sources

        sources = get_active_sources()

        assert sources == []

    def test_maps_all_fields_correctly(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        from datetime import datetime, timezone

        now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
        mock_cursor.fetchall.return_value = [
            (42, "https://rss.example.com/feed", "Test Blog", "DevOps", 7, "active", now, now, now),
        ]

        from src.ingestion.source_loader import get_active_sources

        sources = get_active_sources()

        assert sources[0].id == 42
        assert sources[0].last_checked_at == now
        assert sources[0].created_at == now
        assert sources[0].updated_at == now
