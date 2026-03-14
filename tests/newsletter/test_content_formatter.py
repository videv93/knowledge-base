"""Tests for newsletter content formatter module (Story 4.2)."""

from datetime import date
from unittest.mock import MagicMock

from src.common.models import NewsletterCandidate
from src.newsletter import content_formatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COLUMNS = [
    "post_id", "title", "summary_text", "tags",
    "difficulty_classification", "author_name", "source_name",
    "category", "quality_rating", "publication_date", "url",
    "rank_score", "category_rank",
]


def make_mock_conn(rows):
    """Build a mock DB connection whose cursor returns the given rows."""
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: cur
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    cur.description = [(col,) for col in _COLUMNS]
    cur.fetchall.return_value = rows
    return conn


def _make_row(
    post_id=1,
    title="Test Post",
    summary_text="A test summary.",
    tags=["tag1"],
    difficulty_classification="Intermediate",
    author_name="Author",
    source_name="Source Blog",
    category="Software Engineering",
    quality_rating=4,
    publication_date=date(2026, 3, 1),
    url="https://example.com/post",
    rank_score=100.0,
    category_rank=1,
):
    """Return a tuple row in _COLUMNS order."""
    return (
        post_id, title, summary_text, tags, difficulty_classification,
        author_name, source_name, category, quality_rating,
        publication_date, url, rank_score, category_rank,
    )


def _make_candidate(**kwargs) -> NewsletterCandidate:
    """Return a NewsletterCandidate with sensible defaults."""
    defaults = dict(
        post_id=1, title="Test Post", summary_text="A test summary.",
        tags=["tag1"], difficulty_classification="Intermediate",
        author_name="Author", source_name="Source Blog",
        category="Software Engineering", quality_rating=4,
        publication_date=date(2026, 3, 1), url="https://example.com/post",
        rank_score=100.0, category_rank=1,
    )
    defaults.update(kwargs)
    return NewsletterCandidate(**defaults)


# ---------------------------------------------------------------------------
# Task 2.1 — fetch_candidates returns list of NewsletterCandidates with expected keys
# ---------------------------------------------------------------------------

class TestFetchCandidates:
    def test_returns_list_of_newsletter_candidates(self):
        """fetch_candidates returns a list of NewsletterCandidate dataclasses."""
        conn = make_mock_conn([_make_row()])
        result = content_formatter.fetch_candidates(conn)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], NewsletterCandidate)

    def test_candidate_has_expected_fields(self):
        """Each NewsletterCandidate has all required fields populated."""
        conn = make_mock_conn([_make_row()])
        result = content_formatter.fetch_candidates(conn)
        c = result[0]
        assert hasattr(c, "post_id")
        assert hasattr(c, "title")
        assert hasattr(c, "summary_text")
        assert hasattr(c, "author_name")
        assert hasattr(c, "source_name")
        assert hasattr(c, "url")
        assert hasattr(c, "category")
        assert hasattr(c, "rank_score")

    def test_values_match_row_data(self):
        """Candidate fields correctly reflect row data."""
        row = _make_row(post_id=42, title="Specific Title", rank_score=155.5)
        conn = make_mock_conn([row])
        result = content_formatter.fetch_candidates(conn)
        assert result[0].post_id == 42
        assert result[0].title == "Specific Title"
        assert result[0].rank_score == 155.5

    def test_empty_results(self):
        """Empty result set returns empty list."""
        conn = make_mock_conn([])
        result = content_formatter.fetch_candidates(conn)
        assert result == []

    def test_multiple_rows_returned(self):
        """All rows are returned as candidates."""
        rows = [_make_row(post_id=i, rank_score=float(100 - i)) for i in range(1, 4)]
        conn = make_mock_conn(rows)
        result = content_formatter.fetch_candidates(conn)
        assert len(result) == 3

    def test_null_tags_become_empty_list(self):
        """NULL tags from DB are converted to empty list."""
        row = _make_row(tags=None)
        conn = make_mock_conn([row])
        result = content_formatter.fetch_candidates(conn)
        assert result[0].tags == []

    def test_queries_mart_newsletter_candidates_table(self):
        """SQL query targets mart_newsletter_candidates (mart boundary enforcement)."""
        conn = make_mock_conn([])
        content_formatter.fetch_candidates(conn)
        cur = conn.cursor.return_value
        executed_sql = cur.execute.call_args[0][0]
        assert "mart_newsletter_candidates" in executed_sql

    def test_db_exception_propagates_with_logging(self):
        """Database errors are logged and re-raised."""
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: cur
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        cur.execute.side_effect = RuntimeError("DB connection failed")
        import pytest
        with pytest.raises(RuntimeError, match="DB connection failed"):
            content_formatter.fetch_candidates(conn)


# ---------------------------------------------------------------------------
# Task 2.2 — group_by_category groups and preserves order within category
# ---------------------------------------------------------------------------

class TestGroupByCategory:
    def test_groups_by_category(self):
        """Posts are grouped under their category key."""
        candidates = [
            _make_candidate(post_id=1, category="Software Engineering", rank_score=150.0),
            _make_candidate(post_id=2, category="DevOps & SRE", rank_score=140.0),
            _make_candidate(post_id=3, category="Software Engineering", rank_score=130.0),
        ]
        result = content_formatter.group_by_category(candidates)
        assert "Software Engineering" in result
        assert "DevOps & SRE" in result
        assert len(result["Software Engineering"]) == 2
        assert len(result["DevOps & SRE"]) == 1

    def test_preserves_rank_order_within_category(self):
        """Within a category, posts preserve their original (rank_score DESC) order."""
        candidates = [
            _make_candidate(post_id=1, category="Eng", rank_score=150.0),
            _make_candidate(post_id=2, category="Eng", rank_score=120.0),
        ]
        result = content_formatter.group_by_category(candidates)
        assert result["Eng"][0].rank_score == 150.0
        assert result["Eng"][1].rank_score == 120.0

    def test_category_keys_sorted_alphabetically(self):
        """Category keys are sorted alphabetically."""
        candidates = [
            _make_candidate(post_id=1, category="Zebra"),
            _make_candidate(post_id=2, category="Alpha"),
            _make_candidate(post_id=3, category="Mango"),
        ]
        result = content_formatter.group_by_category(candidates)
        assert list(result.keys()) == ["Alpha", "Mango", "Zebra"]

    def test_empty_list_returns_empty_dict(self):
        """Empty input returns empty dict."""
        result = content_formatter.group_by_category([])
        assert result == {}

    def test_returns_dict(self):
        """Return type is dict."""
        result = content_formatter.group_by_category([_make_candidate()])
        assert isinstance(result, dict)

    def test_none_category_falls_back_to_uncategorized(self):
        """Candidates with category=None are bucketed under 'Uncategorized'."""
        candidate = _make_candidate(category=None)
        result = content_formatter.group_by_category([candidate])
        assert "Uncategorized" in result
        assert len(result["Uncategorized"]) == 1


# ---------------------------------------------------------------------------
# Task 2.3 — format_post_entry contains title, URL, source, author, summary
# ---------------------------------------------------------------------------

class TestFormatPostEntry:
    def test_contains_title(self):
        """Output contains post title."""
        post = _make_candidate(title="My Great Post")
        result = content_formatter.format_post_entry(post)
        assert "My Great Post" in result

    def test_contains_url(self):
        """Output contains post URL."""
        post = _make_candidate(url="https://example.com/my-post")
        result = content_formatter.format_post_entry(post)
        assert "https://example.com/my-post" in result

    def test_contains_source_name(self):
        """Output contains source blog name."""
        post = _make_candidate(source_name="Engineering Digest")
        result = content_formatter.format_post_entry(post)
        assert "Engineering Digest" in result

    def test_contains_author_name(self):
        """Output contains author name."""
        post = _make_candidate(author_name="Jane Doe")
        result = content_formatter.format_post_entry(post)
        assert "Jane Doe" in result

    def test_contains_summary_text(self):
        """Output contains the AI summary text."""
        post = _make_candidate(summary_text="Detailed analysis of distributed systems.")
        result = content_formatter.format_post_entry(post)
        assert "Detailed analysis of distributed systems." in result

    def test_handles_none_summary(self):
        """None summary_text replaced with fallback text."""
        post = _make_candidate(summary_text=None)
        result = content_formatter.format_post_entry(post)
        assert "Summary unavailable" in result

    def test_title_is_clickable_link(self):
        """Title is formatted as a markdown link."""
        post = _make_candidate(title="Click Me", url="https://example.com/click")
        result = content_formatter.format_post_entry(post)
        assert "[Click Me](https://example.com/click)" in result

    def test_empty_url_uses_fallback_not_empty_link(self):
        """Empty URL produces a safe fallback, not a broken empty markdown link."""
        post = _make_candidate(url="")
        result = content_formatter.format_post_entry(post)
        assert "]()" not in result  # No broken empty link


# ---------------------------------------------------------------------------
# Task 2.4 — format_newsletter contains editorial placeholders
# ---------------------------------------------------------------------------

class TestFormatNewsletterPlaceholders:
    def test_includes_editorial_intro_placeholder(self):
        """Editorial intro placeholder is present in output."""
        result = content_formatter.format_newsletter([])
        assert "EDITORIAL INTRO" in result

    def test_includes_editorial_commentary_placeholder(self):
        """Editorial commentary placeholder is present in output."""
        result = content_formatter.format_newsletter([])
        assert "EDITORIAL COMMENTARY" in result

    def test_placeholders_present_with_posts(self):
        """Both placeholders survive when candidates are provided."""
        result = content_formatter.format_newsletter([_make_candidate()])
        assert "EDITORIAL INTRO" in result
        assert "EDITORIAL COMMENTARY" in result


# ---------------------------------------------------------------------------
# Task 2.5 — format_newsletter with multiple categories produces grouped sections
# ---------------------------------------------------------------------------

class TestFormatNewsletterCategoryGrouping:
    def test_multiple_categories_produce_sections(self):
        """Multiple categories each get their own ## section header."""
        candidates = [
            _make_candidate(post_id=1, category="Software Engineering", title="Post A"),
            _make_candidate(post_id=2, category="DevOps & SRE", title="Post B"),
            _make_candidate(post_id=3, category="Data Engineering", title="Post C"),
        ]
        result = content_formatter.format_newsletter(candidates)
        assert "## Software Engineering" in result
        assert "## DevOps & SRE" in result
        assert "## Data Engineering" in result

    def test_posts_appear_under_correct_category(self):
        """Alpha category appears before Beta, and each post is under its own category."""
        candidates = [
            _make_candidate(post_id=1, category="Alpha", title="Alpha Post"),
            _make_candidate(post_id=2, category="Beta", title="Beta Post"),
        ]
        result = content_formatter.format_newsletter(candidates)
        lines = result.splitlines()
        alpha_header_line = next(i for i, l in enumerate(lines) if l == "## Alpha")
        beta_header_line = next(i for i, l in enumerate(lines) if l == "## Beta")
        alpha_post_line = next(i for i, l in enumerate(lines) if "Alpha Post" in l)
        beta_post_line = next(i for i, l in enumerate(lines) if "Beta Post" in l)
        assert alpha_header_line < alpha_post_line < beta_header_line < beta_post_line

    def test_returns_string(self):
        """format_newsletter always returns a string."""
        assert isinstance(content_formatter.format_newsletter([]), str)


# ---------------------------------------------------------------------------
# Task 2.6 — generate_newsletter_content integration with mocked DB
# ---------------------------------------------------------------------------

class TestGenerateNewsletterContent:
    def test_returns_string(self):
        """generate_newsletter_content returns a string."""
        conn = make_mock_conn([])
        assert isinstance(content_formatter.generate_newsletter_content(conn), str)

    def test_integration_with_mocked_db(self):
        """Full pipeline integration: fetch → group → format with mock conn."""
        rows = [
            _make_row(post_id=1, title="Pipeline Post", category="Data Engineering",
                      author_name="Alice", source_name="Data Blog",
                      url="https://example.com/pipeline", rank_score=150.0),
        ]
        conn = make_mock_conn(rows)
        result = content_formatter.generate_newsletter_content(conn)
        assert "Pipeline Post" in result
        assert "Data Engineering" in result
        assert "Alice" in result
        assert "Data Blog" in result

    def test_uses_provided_conn_not_internal_connection(self):
        """generate_newsletter_content uses the passed conn, calls cursor()."""
        conn = make_mock_conn([])
        content_formatter.generate_newsletter_content(conn)
        conn.cursor.assert_called()

    def test_editorial_placeholders_present(self):
        """Output includes editorial placeholders regardless of content."""
        conn = make_mock_conn([])
        result = content_formatter.generate_newsletter_content(conn)
        assert "EDITORIAL INTRO" in result
        assert "EDITORIAL COMMENTARY" in result

    def test_db_exception_propagates(self):
        """Database errors bubble up from generate_newsletter_content."""
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda s: cur
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        cur.execute.side_effect = RuntimeError("Connection lost")
        import pytest
        with pytest.raises(RuntimeError, match="Connection lost"):
            content_formatter.generate_newsletter_content(conn)


# ---------------------------------------------------------------------------
# Task 2.7 — empty candidates list produces valid newsletter with placeholders
# ---------------------------------------------------------------------------

class TestEmptyCandidates:
    def test_empty_list_produces_valid_newsletter(self):
        """Empty candidates list returns string with both placeholders."""
        result = content_formatter.format_newsletter([])
        assert isinstance(result, str)
        assert "EDITORIAL INTRO" in result
        assert "EDITORIAL COMMENTARY" in result

    def test_empty_list_has_no_category_headers(self):
        """Empty candidates list produces no ## category headers."""
        result = content_formatter.format_newsletter([])
        category_headers = [l for l in result.splitlines() if l.startswith("## ")]
        assert category_headers == []

    def test_empty_fetch_produces_minimal_newsletter(self):
        """fetch + format pipeline with no DB rows gives minimal newsletter."""
        conn = make_mock_conn([])
        result = content_formatter.generate_newsletter_content(conn)
        assert "EDITORIAL INTRO" in result
        assert "EDITORIAL COMMENTARY" in result
