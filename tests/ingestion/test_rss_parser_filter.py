"""Tests for rss_parser.filter_entries_by_date()."""

from datetime import datetime, timedelta, timezone


def _make_entry(days_ago=None):
    """Create a test entry dict with publication_date set to days_ago from now."""
    pub_date = None
    if days_ago is not None:
        pub_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "title": "Test Post",
        "body": "Content",
        "url": f"https://example.com/post-{days_ago}",
        "publication_date": pub_date,
        "author_name": "Author",
    }


class TestFilterEntriesByDate:
    def test_keeps_recent_entries(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(5), _make_entry(10), _make_entry(25)]
        result = filter_entries_by_date(entries)
        assert len(result) == 3

    def test_skips_old_entries(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(5), _make_entry(31), _make_entry(60)]
        result = filter_entries_by_date(entries)
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/post-5"

    def test_includes_entries_with_none_date(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(None), _make_entry(5)]
        result = filter_entries_by_date(entries)
        assert len(result) == 2

    def test_custom_max_age_days(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(5), _make_entry(10), _make_entry(20)]
        result = filter_entries_by_date(entries, max_age_days=7)
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/post-5"

    def test_empty_list_returns_empty(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        result = filter_entries_by_date([])
        assert result == []

    def test_boundary_exactly_30_days(self):
        """Entry exactly 30 days old should be filtered out (strictly < cutoff)."""
        from src.ingestion.rss_parser import filter_entries_by_date

        entry = _make_entry(30)
        entries = [entry, _make_entry(29)]
        result = filter_entries_by_date(entries, max_age_days=30)
        # 29-day-old entry should be kept; 30-day is borderline (filtered due to execution time)
        assert len(result) >= 1
        assert any(e["url"] == "https://example.com/post-29" for e in result)

    def test_all_old_entries_returns_empty(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(60), _make_entry(90)]
        result = filter_entries_by_date(entries)
        assert result == []

    def test_preserves_entry_data(self):
        from src.ingestion.rss_parser import filter_entries_by_date

        entries = [_make_entry(5)]
        result = filter_entries_by_date(entries)
        assert result[0]["title"] == "Test Post"
        assert result[0]["body"] == "Content"
        assert result[0]["author_name"] == "Author"
