"""Tests for src/ingestion/pipeline.py."""

from unittest.mock import patch

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


class TestRunIngestion:
    """Tests for run_ingestion function."""

    @patch("src.ingestion.pipeline.ingest_posts")
    @patch("src.ingestion.pipeline.parse_feed")
    @patch("src.ingestion.pipeline._update_last_checked")
    def test_processes_multiple_sources(self, mock_update, mock_parse, mock_ingest):
        from src.ingestion.pipeline import run_ingestion

        mock_parse.return_value = [{"title": "Post", "url": "http://x.com/1", "body": "", "author_name": "A", "publication_date": None}]
        mock_ingest.return_value = {"success_count": 1, "duplicate_count": 0, "failure_count": 0}

        sources = [_make_source(id=1, name="Blog A"), _make_source(id=2, name="Blog B")]
        metrics = run_ingestion(sources)

        assert metrics["sources_processed"] == 2
        assert metrics["sources_failed"] == 0
        assert metrics["total_success"] == 2
        assert mock_parse.call_count == 2
        assert mock_ingest.call_count == 2

    @patch("src.ingestion.pipeline.ingest_posts")
    @patch("src.ingestion.pipeline.parse_feed")
    @patch("src.ingestion.pipeline._update_last_checked")
    def test_one_source_failure_doesnt_block_others(self, mock_update, mock_parse, mock_ingest):
        from src.ingestion.pipeline import run_ingestion

        def parse_side_effect(source):
            if source.name == "Bad Blog":
                raise Exception("Parse error")
            return [{"title": "Post", "url": "http://x.com/1", "body": "", "author_name": "A", "publication_date": None}]

        mock_parse.side_effect = parse_side_effect
        mock_ingest.return_value = {"success_count": 1, "duplicate_count": 0, "failure_count": 0}

        sources = [
            _make_source(id=1, name="Good Blog"),
            _make_source(id=2, name="Bad Blog"),
            _make_source(id=3, name="Another Good"),
        ]
        metrics = run_ingestion(sources)

        assert metrics["sources_processed"] == 2
        assert metrics["sources_failed"] == 1
        assert metrics["total_success"] == 2

    @patch("src.ingestion.pipeline.ingest_posts")
    @patch("src.ingestion.pipeline.parse_feed")
    @patch("src.ingestion.pipeline._update_last_checked")
    def test_last_checked_updated_for_processed_sources(self, mock_update, mock_parse, mock_ingest):
        from src.ingestion.pipeline import run_ingestion

        mock_parse.return_value = [{"title": "Post", "url": "http://x.com/1", "body": "", "author_name": "A", "publication_date": None}]
        mock_ingest.return_value = {"success_count": 1, "duplicate_count": 0, "failure_count": 0}

        source = _make_source(id=42)
        run_ingestion([source])

        mock_update.assert_called_once_with(42)
