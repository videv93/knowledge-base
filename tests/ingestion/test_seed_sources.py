"""Tests for src.ingestion.seed_sources."""

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


SEED_CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "blog_sources.csv"


class TestSeedDataFile:
    """Validate the committed seed data CSV."""

    def test_seed_csv_exists(self):
        assert SEED_CSV_PATH.exists(), f"Seed CSV not found at {SEED_CSV_PATH}"

    def test_seed_csv_has_211_rows(self):
        with open(SEED_CSV_PATH) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 211

    def test_seed_csv_has_10_categories(self):
        with open(SEED_CSV_PATH) as f:
            reader = csv.DictReader(f)
            categories = {row["category"] for row in reader}
        assert len(categories) == 10
        expected = {
            "AI/ML & LLMs",
            "Backend Engineering",
            "Cloud Platforms",
            "Data Engineering & Databases",
            "DevOps & Infrastructure",
            "Frontend Engineering",
            "Platform & SRE",
            "Product Management & Growth",
            "Security & Privacy",
            "UX/UI Design",
        }
        assert categories == expected

    def test_seed_csv_quality_ratings_valid(self):
        with open(SEED_CSV_PATH) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rating = int(row["quality_rating"])
                assert 1 <= rating <= 5, f"Invalid rating {rating} for {row['name']}"

    def test_seed_csv_rss_urls_not_empty(self):
        with open(SEED_CSV_PATH) as f:
            reader = csv.DictReader(f)
            for row in reader:
                assert row["rss_feed_url"].strip(), f"Empty RSS URL for {row['name']}"
                assert row["rss_feed_url"].startswith("http"), f"Invalid RSS URL for {row['name']}: {row['rss_feed_url']}"

    def test_seed_csv_has_required_columns(self):
        with open(SEED_CSV_PATH) as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
        assert "name" in headers
        assert "rss_feed_url" in headers
        assert "blog_url" in headers
        assert "category" in headers
        assert "quality_rating" in headers


class TestLoadSources:
    """Test the load_sources function."""

    def _make_csv(self, tmp_path, rows):
        """Create a temporary CSV file with given rows."""
        csv_path = tmp_path / "test_sources.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "rss_feed_url", "blog_url", "category", "quality_rating"])
            for row in rows:
                writer.writerow(row)
        return str(csv_path)

    @patch("src.ingestion.seed_sources.execute_values")
    def test_load_sources_inserts_rows(self, mock_ev, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.side_effect = [(0,), (3,)]

        csv_path = self._make_csv(tmp_path, [
            ["Blog A", "https://a.com/feed", "https://a.com", "AI/ML & LLMs", 5],
            ["Blog B", "https://b.com/feed", "https://b.com", "Backend Engineering", 4],
            ["Blog C", "https://c.com/feed", "https://c.com", "Cloud Platforms", 3],
        ])

        from src.ingestion.seed_sources import load_sources
        metrics = load_sources(csv_path)

        assert metrics == {"inserted": 3, "skipped": 0, "total": 3}
        mock_ev.assert_called_once()

    @patch("src.ingestion.seed_sources.execute_values")
    def test_load_sources_idempotent(self, mock_ev, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.side_effect = [(3,), (3,)]

        csv_path = self._make_csv(tmp_path, [
            ["Blog A", "https://a.com/feed", "https://a.com", "AI/ML & LLMs", 5],
            ["Blog B", "https://b.com/feed", "https://b.com", "Backend Engineering", 4],
            ["Blog C", "https://c.com/feed", "https://c.com", "Cloud Platforms", 3],
        ])

        from src.ingestion.seed_sources import load_sources
        metrics = load_sources(csv_path)

        assert metrics == {"inserted": 0, "skipped": 3, "total": 3}

    @patch("src.ingestion.seed_sources.execute_values")
    def test_load_sources_returns_correct_metrics(self, mock_ev, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.side_effect = [(1,), (3,)]

        csv_path = self._make_csv(tmp_path, [
            ["Blog A", "https://a.com/feed", "https://a.com", "AI/ML & LLMs", 5],
            ["Blog B", "https://b.com/feed", "https://b.com", "Backend Engineering", 4],
            ["Blog C", "https://c.com/feed", "https://c.com", "Cloud Platforms", 3],
        ])

        from src.ingestion.seed_sources import load_sources
        metrics = load_sources(csv_path)

        assert metrics["inserted"] == 2
        assert metrics["skipped"] == 1
        assert metrics["total"] == 3

    def test_load_sources_file_not_found(self, mock_db_connection):
        from src.ingestion.seed_sources import load_sources
        with pytest.raises(FileNotFoundError):
            load_sources("/nonexistent/path.csv")

    def test_load_sources_uses_execute_values(self, mock_db_connection, tmp_path):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchone.side_effect = [(0,), (2,)]

        csv_path = self._make_csv(tmp_path, [
            ["Blog A", "https://a.com/feed", "https://a.com", "AI/ML & LLMs", 5],
            ["Blog B", "https://b.com/feed", "https://b.com", "Backend Engineering", 4],
        ])

        with patch("src.ingestion.seed_sources.execute_values") as mock_ev:
            from src.ingestion.seed_sources import load_sources
            load_sources(csv_path)

            mock_ev.assert_called_once()
            args = mock_ev.call_args
            assert "ON CONFLICT" in args[0][1]
            assert len(args[0][2]) == 2  # 2 rows
