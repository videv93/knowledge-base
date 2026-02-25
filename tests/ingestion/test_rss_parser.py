"""Tests for src/ingestion/rss_parser.py."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import feedparser

from src.common.models import BlogSource

FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


class TestParseFeed:
    """Tests for parse_feed function."""

    def test_rss2_feed_extracts_correct_fields(self):
        """Test RSS 2.0 feed parsing extracts title, url, body, author, date."""
        from src.ingestion.rss_parser import parse_feed

        feed_content = (FIXTURES_DIR / "sample_rss.xml").read_text()
        parsed = feedparser.parse(feed_content)

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=parsed):
            source = _make_source()
            entries = parse_feed(source)

        assert len(entries) == 2
        assert entries[0]["title"] == "Test Post Title"
        assert entries[0]["url"] == "https://testblog.com/post-1"
        assert entries[0]["body"] == "This is the post summary content."
        assert entries[0]["author_name"] == "Jane Doe"
        assert isinstance(entries[0]["publication_date"], datetime)

    def test_atom_feed_extracts_correct_fields(self):
        """Test Atom feed parsing extracts correct fields including content."""
        from src.ingestion.rss_parser import parse_feed

        feed_content = (FIXTURES_DIR / "sample_atom.xml").read_text()
        parsed = feedparser.parse(feed_content)

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=parsed):
            source = _make_source(rss_feed_url="https://atomblog.com/feed")
            entries = parse_feed(source)

        assert len(entries) == 1
        assert entries[0]["title"] == "Atom Post Title"
        assert entries[0]["url"] == "https://atomblog.com/post-1"
        assert entries[0]["body"] == "Full content of the Atom post."
        assert entries[0]["author_name"] == "John Smith"

    def test_malformed_feed_returns_partial_entries(self):
        """Test malformed feed with bozo flag returns whatever entries parsed successfully."""
        from src.ingestion.rss_parser import parse_feed

        feed_content = (FIXTURES_DIR / "sample_malformed.xml").read_text()
        parsed = feedparser.parse(feed_content)
        # feedparser sets bozo=True for malformed feeds

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=parsed):
            source = _make_source()
            entries = parse_feed(source)

        # Should return valid entries only (those with url and title)
        for entry in entries:
            assert entry["url"]
            assert entry["title"]

    def test_unreachable_feed_routes_to_dlq(self):
        """Test that a feed fetch exception routes to DLQ and returns empty list."""
        from src.ingestion.rss_parser import parse_feed

        with patch("src.ingestion.rss_parser.feedparser.parse", side_effect=Exception("Connection refused")), \
             patch("src.ingestion.rss_parser.dlq") as mock_dlq:
            source = _make_source()
            entries = parse_feed(source)

        assert entries == []
        mock_dlq.route_to_dlq.assert_called_once()
        args = mock_dlq.route_to_dlq.call_args[0]
        assert args[1] == "ingestion"

    def test_entry_missing_url_is_skipped(self):
        """Test that entries without a URL are skipped with WARNING log."""
        from src.ingestion.rss_parser import parse_feed

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_entry_good = MagicMock()
        mock_entry_good.get.side_effect = lambda k, d="": {
            "title": "Good Post",
            "link": "https://example.com/post-1",
            "author": "Author",
        }.get(k, d)
        mock_entry_good.content = []
        mock_entry_good.summary = "Summary"

        mock_entry_bad = MagicMock()
        mock_entry_bad.get.side_effect = lambda k, d="": {
            "title": "Bad Post",
            "link": "",
            "author": "Author",
        }.get(k, d)

        mock_feed.entries = [mock_entry_good, mock_entry_bad]

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=mock_feed):
            source = _make_source()
            entries = parse_feed(source)

        # Only the good entry should be returned
        assert len(entries) == 1
        assert entries[0]["title"] == "Good Post"

    def test_publication_date_parsing(self):
        """Test publication_date is correctly parsed from time struct to UTC datetime."""
        from src.ingestion.rss_parser import parse_feed

        feed_content = (FIXTURES_DIR / "sample_rss.xml").read_text()
        parsed = feedparser.parse(feed_content)

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=parsed):
            source = _make_source()
            entries = parse_feed(source)

        pub_date = entries[0]["publication_date"]
        assert pub_date.tzinfo is not None
        assert pub_date.tzinfo == timezone.utc

    def test_author_fallback_to_unknown(self):
        """Test author defaults to 'Unknown' when not provided."""
        from src.ingestion.rss_parser import parse_feed

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda k, d="": {
            "title": "No Author Post",
            "link": "https://example.com/no-author",
            "author": "",
        }.get(k, d)
        mock_entry.content = []
        mock_entry.summary = "Summary"
        mock_feed.entries = [mock_entry]
        # No author_detail attribute
        del mock_entry.author_detail

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=mock_feed):
            source = _make_source()
            entries = parse_feed(source)

        assert len(entries) == 1
        assert entries[0]["author_name"] == "Unknown"

    def test_body_fallback_chain(self):
        """Test body extraction: content → summary → description → empty string."""
        from src.ingestion.rss_parser import parse_feed

        # Test fallback to summary when no content
        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_entry = MagicMock()
        mock_entry.get.side_effect = lambda k, d="": {
            "title": "Fallback Post",
            "link": "https://example.com/fallback",
            "author": "Author",
        }.get(k, d)
        mock_entry.content = []
        mock_entry.summary = "Summary body text"
        mock_feed.entries = [mock_entry]

        with patch("src.ingestion.rss_parser.feedparser.parse", return_value=mock_feed):
            source = _make_source()
            entries = parse_feed(source)

        assert entries[0]["body"] == "Summary body text"
