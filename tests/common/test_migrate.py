"""Tests for src.common.migrate module."""

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_get_migration_files_returns_sorted(tmp_path):
    """get_migration_files() returns SQL files sorted by name."""
    (tmp_path / "002_second.sql").write_text("SELECT 1;")
    (tmp_path / "001_first.sql").write_text("SELECT 1;")
    (tmp_path / "003_third.sql").write_text("SELECT 1;")
    (tmp_path / "README.md").write_text("not sql")

    from src.common.migrate import get_migration_files

    files = get_migration_files(tmp_path)

    assert len(files) == 3
    assert files[0].name == "001_first.sql"
    assert files[1].name == "002_second.sql"
    assert files[2].name == "003_third.sql"


def test_get_migration_files_returns_empty_for_missing_dir():
    """get_migration_files() returns empty list for nonexistent directory."""
    from src.common.migrate import get_migration_files

    files = get_migration_files(Path("/nonexistent/dir"))

    assert files == []


def test_run_migrations_executes_in_order(tmp_path):
    """run_migrations() executes SQL files in sorted order."""
    (tmp_path / "001_first.sql").write_text("CREATE TABLE IF NOT EXISTS t1 (id INT);")
    (tmp_path / "002_second.sql").write_text("CREATE TABLE IF NOT EXISTS t2 (id INT);")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.migrate.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        from src.common.migrate import run_migrations

        executed = run_migrations(tmp_path)

    assert executed == ["001_first.sql", "002_second.sql"]
    assert mock_cursor.execute.call_count == 2
    mock_cursor.execute.assert_any_call("CREATE TABLE IF NOT EXISTS t1 (id INT);")
    mock_cursor.execute.assert_any_call("CREATE TABLE IF NOT EXISTS t2 (id INT);")


def test_run_migrations_idempotent(tmp_path):
    """run_migrations() can be called twice without error (idempotent SQL)."""
    (tmp_path / "001_first.sql").write_text("CREATE TABLE IF NOT EXISTS t1 (id INT);")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.migrate.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        from src.common.migrate import run_migrations

        first_run = run_migrations(tmp_path)
        second_run = run_migrations(tmp_path)

    assert first_run == ["001_first.sql"]
    assert second_run == ["001_first.sql"]


def test_run_migrations_returns_empty_for_no_files(tmp_path):
    """run_migrations() returns empty list when no SQL files exist."""
    from src.common.migrate import run_migrations

    with patch("src.common.migrate.get_connection"):
        executed = run_migrations(tmp_path)

    assert executed == []


def test_run_migrations_logs_failed_migration(tmp_path):
    """run_migrations() logs the failing migration name and re-raises."""
    (tmp_path / "001_first.sql").write_text("CREATE TABLE IF NOT EXISTS t1 (id INT);")
    (tmp_path / "002_bad.sql").write_text("INVALID SQL;")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = [None, Exception("syntax error")]
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("src.common.migrate.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)

        from src.common.migrate import run_migrations

        import pytest
        with pytest.raises(Exception, match="syntax error"):
            run_migrations(tmp_path)


def test_migration_sql_files_are_valid():
    """All migration SQL files in the migrations/ directory contain valid SQL structure."""
    from src.common.migrate import MIGRATIONS_DIR, get_migration_files

    files = get_migration_files(MIGRATIONS_DIR)

    assert len(files) >= 3, f"Expected at least 3 migration files, found {len(files)}"

    for f in files:
        sql = f.read_text()
        has_create = "CREATE TABLE" in sql
        has_alter = "ALTER TABLE" in sql
        assert has_create or has_alter, f"{f.name} missing CREATE TABLE or ALTER TABLE statement"
        has_idempotent = "IF NOT EXISTS" in sql or "DO $$" in sql
        assert has_idempotent, f"{f.name} missing idempotency guard (IF NOT EXISTS or DO $$ block)"


def test_migration_001_raw_blog_sources_schema():
    """001 migration creates raw_blog_sources with correct columns."""
    from src.common.migrate import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "001_create_raw_blog_sources.sql").read_text()

    for col in ["id", "rss_feed_url", "name", "category", "quality_rating",
                "status", "last_checked_at", "created_at", "updated_at"]:
        assert col in sql, f"Missing column: {col}"

    assert "GENERATED ALWAYS AS IDENTITY" in sql
    assert "TIMESTAMPTZ" in sql


def test_migration_002_raw_blog_posts_schema():
    """002 migration creates raw_blog_posts with FK, unique constraint, and index."""
    from src.common.migrate import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "002_create_raw_blog_posts.sql").read_text()

    for col in ["id", "source_id", "title", "body", "url",
                "publication_date", "author_name", "created_at"]:
        assert col in sql, f"Missing column: {col}"

    assert "REFERENCES raw_blog_sources(id)" in sql
    assert "uq_raw_blog_posts_url" in sql
    assert "idx_raw_blog_posts_source_id" in sql
    assert "GENERATED ALWAYS AS IDENTITY" in sql


def test_migration_003_dead_letter_posts_schema():
    """003 migration creates dead_letter_posts matching dlq.py column contract."""
    from src.common.migrate import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "003_create_dead_letter_posts.sql").read_text()

    for col in ["id", "post_reference", "failure_stage", "failure_reason",
                "retry_count", "created_at", "last_retry_at"]:
        assert col in sql, f"Missing column: {col}"

    assert "GENERATED ALWAYS AS IDENTITY" in sql
