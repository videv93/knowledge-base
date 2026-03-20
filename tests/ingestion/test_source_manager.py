"""Tests for src/ingestion/source_manager.py."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


class TestAddSource:
    """Tests for add_source()."""

    def test_inserts_new_source(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = (42,)

        from src.ingestion.source_manager import add_source

        result = add_source("https://blog.example.com/rss", "Example Blog", "Software Engineering", 8)

        assert result == {"action": "inserted", "source_id": 42}

    def test_returns_skipped_for_duplicate_url(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None

        from src.ingestion.source_manager import add_source

        result = add_source("https://blog.example.com/rss", "Example Blog", "Software Engineering", 8)

        assert result == {"action": "skipped", "reason": "duplicate"}

    def test_validates_empty_url_raises_error(self, mock_db_connection):
        from src.ingestion.source_manager import add_source

        with pytest.raises(ValueError, match="rss_feed_url must not be empty"):
            add_source("", "Blog", "Category", 5)

    def test_validates_empty_name_raises_error(self, mock_db_connection):
        from src.ingestion.source_manager import add_source

        with pytest.raises(ValueError, match="name must not be empty"):
            add_source("https://example.com/rss", "", "Category", 5)

    def test_validates_empty_category_raises_error(self, mock_db_connection):
        from src.ingestion.source_manager import add_source

        with pytest.raises(ValueError, match="category must not be empty"):
            add_source("https://example.com/rss", "Blog", "", 5)

    def test_validates_quality_rating_too_low(self, mock_db_connection):
        from src.ingestion.source_manager import add_source

        with pytest.raises(ValueError, match="quality_rating must be an integer between 1 and 10"):
            add_source("https://example.com/rss", "Blog", "Category", 0)

    def test_validates_quality_rating_too_high(self, mock_db_connection):
        from src.ingestion.source_manager import add_source

        with pytest.raises(ValueError, match="quality_rating must be an integer between 1 and 10"):
            add_source("https://example.com/rss", "Blog", "Category", 11)

    def test_uses_parameterized_query(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = (1,)

        from src.ingestion.source_manager import add_source

        add_source("https://blog.example.com/rss", "Example Blog", "Software Engineering", 8)

        executed_sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        assert "%s" in executed_sql
        assert params == ("https://blog.example.com/rss", "Example Blog", "Software Engineering", 8)

    def test_uses_on_conflict_do_nothing(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = (1,)

        from src.ingestion.source_manager import add_source

        add_source("https://blog.example.com/rss", "Example Blog", "Software Engineering", 8)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "ON CONFLICT (rss_feed_url) DO NOTHING" in executed_sql


class TestDeactivateSource:
    """Tests for deactivate_source()."""

    def test_sets_status_to_inactive(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import deactivate_source

        result = deactivate_source(42)

        assert result == {"action": "deactivated", "source_id": 42}
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "status = 'inactive'" in executed_sql

    def test_updates_updated_at_timestamp(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import deactivate_source

        deactivate_source(42)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "updated_at = NOW()" in executed_sql

    def test_returns_not_found_for_nonexistent(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 0

        from src.ingestion.source_manager import deactivate_source

        result = deactivate_source(9999)

        assert result == {"action": "not_found", "source_id": 9999}


class TestActivateSource:
    """Tests for activate_source()."""

    def test_sets_status_to_active(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import activate_source

        result = activate_source(42)

        assert result == {"action": "activated", "source_id": 42}
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "status = 'active'" in executed_sql

    def test_updates_updated_at_timestamp(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import activate_source

        activate_source(42)

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "updated_at = NOW()" in executed_sql

    def test_returns_not_found_for_nonexistent(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 0

        from src.ingestion.source_manager import activate_source

        result = activate_source(9999)

        assert result == {"action": "not_found", "source_id": 9999}


class TestUpdateSource:
    """Tests for update_source()."""

    def test_updates_specified_fields(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import update_source

        result = update_source(42, name="New Name", category="New Category")

        assert result["action"] == "updated"
        assert sorted(result["fields"]) == ["category", "name"]

    def test_rejects_unknown_fields(self, mock_db_connection):
        from src.ingestion.source_manager import update_source

        with pytest.raises(ValueError, match="Unknown fields"):
            update_source(42, unknown_field="value")

    def test_sets_updated_at(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import update_source

        update_source(42, name="New Name")

        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "updated_at = NOW()" in executed_sql

    def test_updates_single_field(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import update_source

        result = update_source(42, quality_rating=9)

        assert result == {"action": "updated", "fields": ["quality_rating"]}

    def test_rejects_empty_string_value(self, mock_db_connection):
        from src.ingestion.source_manager import update_source

        with pytest.raises(ValueError, match="Empty value for field"):
            update_source(42, name="")

    def test_rejects_no_fields(self, mock_db_connection):
        from src.ingestion.source_manager import update_source

        with pytest.raises(ValueError, match="No fields provided"):
            update_source(42)

    def test_returns_not_found_for_nonexistent(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 0

        from src.ingestion.source_manager import update_source

        result = update_source(9999, name="New Name")

        assert result == {"action": "not_found", "source_id": 9999}

    def test_sql_params_match_set_clause_order(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.rowcount = 1

        from src.ingestion.source_manager import update_source

        update_source(42, name="New Name", quality_rating=9)

        executed_sql = mock_cursor.execute.call_args[0][0]
        params = mock_cursor.execute.call_args[0][1]
        # Verify params contain the field values in the same order as
        # they appear in the SET clause, followed by source_id for WHERE
        assert params[-1] == 42  # source_id is last (WHERE clause)
        # The non-id params should match the SET clause field order
        if "name" in executed_sql.split("quality_rating")[0]:
            assert params[:-1] == ("New Name", 9)
        else:
            assert params[:-1] == (9, "New Name")


class TestGetSourceById:
    """Tests for get_source_by_id()."""

    def test_returns_blog_source_for_existing(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        now = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        mock_cursor.fetchone.return_value = (
            42, "https://blog.example.com/rss", "Example Blog",
            "Software Engineering", 8, "active", now, now, now,
        )

        from src.ingestion.source_manager import get_source_by_id

        source = get_source_by_id(42)

        assert source is not None
        assert source.id == 42
        assert source.name == "Example Blog"
        assert source.rss_feed_url == "https://blog.example.com/rss"
        assert source.category == "Software Engineering"
        assert source.quality_rating == 8
        assert source.status == "active"

    def test_returns_none_for_nonexistent(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.return_value = None

        from src.ingestion.source_manager import get_source_by_id

        source = get_source_by_id(9999)

        assert source is None


FROZEN_NOW = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)


class TestGetSourceHealth:
    """Tests for get_source_health()."""

    @patch("src.ingestion.source_manager.datetime")
    def test_returns_health_metrics(self, mock_datetime, mock_db_connection):
        mock_datetime.now.return_value = FROZEN_NOW
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, "Blog A", "Engineering", "active", 8, 50, FROZEN_NOW, FROZEN_NOW, FROZEN_NOW),
        ]

        from src.ingestion.source_manager import get_source_health

        results = get_source_health()

        assert len(results) == 1
        assert results[0]["id"] == 1
        assert results[0]["name"] == "Blog A"
        assert results[0]["total_post_count"] == 50
        assert results[0]["is_unhealthy"] is False

    @patch("src.ingestion.source_manager.datetime")
    def test_flags_unhealthy_sources_inactive(self, mock_datetime, mock_db_connection):
        mock_datetime.now.return_value = FROZEN_NOW
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, "Blog A", "Engineering", "inactive", 8, 50, FROZEN_NOW, FROZEN_NOW, FROZEN_NOW),
        ]

        from src.ingestion.source_manager import get_source_health

        results = get_source_health()

        assert results[0]["is_unhealthy"] is True

    @patch("src.ingestion.source_manager.datetime")
    def test_flags_unhealthy_sources_zero_posts_old(self, mock_datetime, mock_db_connection):
        mock_datetime.now.return_value = FROZEN_NOW
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_conn, mock_cursor = mock_db_connection
        old_date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_cursor.fetchall.return_value = [
            (1, "Blog A", "Engineering", "active", 8, 0, None, FROZEN_NOW, old_date),
        ]

        from src.ingestion.source_manager import get_source_health

        results = get_source_health()

        assert results[0]["is_unhealthy"] is True

    @patch("src.ingestion.source_manager.datetime")
    def test_flags_unhealthy_sources_stale_check(self, mock_datetime, mock_db_connection):
        mock_datetime.now.return_value = FROZEN_NOW
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_conn, mock_cursor = mock_db_connection
        stale_date = datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc)
        mock_cursor.fetchall.return_value = [
            (1, "Blog A", "Engineering", "active", 8, 50, FROZEN_NOW, stale_date, FROZEN_NOW),
        ]

        from src.ingestion.source_manager import get_source_health

        results = get_source_health()

        assert results[0]["is_unhealthy"] is True

    @patch("src.ingestion.source_manager.datetime")
    def test_returns_empty_list_when_no_sources(self, mock_datetime, mock_db_connection):
        mock_datetime.now.return_value = FROZEN_NOW
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = []

        from src.ingestion.source_manager import get_source_health

        results = get_source_health()

        assert results == []
