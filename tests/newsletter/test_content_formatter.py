"""Tests for newsletter content formatter module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.common.models import NewsletterCandidate
from src.newsletter import content_formatter


@pytest.fixture
def sample_candidates():
    """Load sample newsletter candidates from fixtures."""
    fixtures_path = Path(__file__).parent / "fixtures" / "sample_candidates.json"
    with open(fixtures_path) as f:
        data = json.load(f)

    candidates = []
    for item in data:
        candidate = NewsletterCandidate(
            id=item["id"],
            source_id=item["source_id"],
            title=item["title"],
            url=item["url"],
            summary_text=item["summary_text"],
            author_name=item["author_name"],
            source_name=item["source_name"],
            category=item["category"],
            publication_date=datetime.fromisoformat(item["publication_date"]),
            tags=item["tags"],
            difficulty_classification=item["difficulty_classification"],
            score=item["score"]
        )
        candidates.append(candidate)

    return candidates


class TestFetchNewsletterCandidates:
    """Tests for fetch_newsletter_candidates() function."""

    @patch("src.newsletter.content_formatter.db.get_connection")
    def test_fetch_returns_newsletter_candidates(self, mock_get_conn, sample_candidates):
        """Verify fetch returns list of NewsletterCandidate objects."""
        # Arrange: Mock database rows
        mock_rows = [
            (c.id, c.source_id, c.title, c.url, c.summary_text, c.author_name,
             c.source_name, c.category, c.publication_date, c.tags,
             c.difficulty_classification, c.score)
            for c in sample_candidates
        ]

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_get_conn.return_value = mock_conn

        # Act
        result = content_formatter.fetch_newsletter_candidates()

        # Assert
        assert len(result) == 3
        assert all(isinstance(c, NewsletterCandidate) for c in result)
        assert result[0].title == "Understanding Event-Driven Architecture"
        assert result[1].category == "DevOps & SRE"
        assert result[2].score == 138.7

    @patch("src.newsletter.content_formatter.db.get_connection")
    def test_fetch_handles_empty_results(self, mock_get_conn):
        """Verify empty results handled gracefully."""
        # Arrange
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_get_conn.return_value = mock_conn

        # Act
        result = content_formatter.fetch_newsletter_candidates()

        # Assert
        assert result == []
        assert isinstance(result, list)

    @patch("src.newsletter.content_formatter.db.get_connection")
    def test_fetch_handles_null_tags(self, mock_get_conn):
        """Verify NULL JSONB tags handled correctly."""
        # Arrange: Mock row with NULL tags
        mock_rows = [(1, 10, "Test Title", "https://example.com", "Summary text",
                      "Author", "Source", "Category", datetime.now(), None,
                      "Intermediate", 100.0)]

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_get_conn.return_value = mock_conn

        # Act
        result = content_formatter.fetch_newsletter_candidates()

        # Assert
        assert len(result) == 1
        assert result[0].tags == []  # NULL should become empty list


class TestGroupByCategory:
    """Tests for group_by_category() function."""

    def test_interleaves_multiple_categories(self, sample_candidates):
        """Verify categories are interleaved round-robin."""
        # Act
        result = content_formatter.group_by_category(sample_candidates)

        # Assert
        assert len(result) == 3
        # First post from each category (since each has 1 post)
        assert result[0].category == "Software Engineering"
        assert result[1].category == "DevOps & SRE"
        assert result[2].category == "Data Engineering"

    def test_preserves_score_order_within_category(self):
        """Verify score order preserved within each category."""
        # Arrange: Multiple posts in same category
        candidates = [
            NewsletterCandidate(1, 10, "Post A", "http://a", "Summary A", "Author",
                                "Source", "Category A", datetime.now(), [], "Intermediate", 150.0),
            NewsletterCandidate(2, 10, "Post B", "http://b", "Summary B", "Author",
                                "Source", "Category A", datetime.now(), [], "Intermediate", 140.0),
            NewsletterCandidate(3, 10, "Post C", "http://c", "Summary C", "Author",
                                "Source", "Category B", datetime.now(), [], "Intermediate", 130.0),
        ]

        # Act
        result = content_formatter.group_by_category(candidates)

        # Assert
        # Should interleave: Category A (150), Category B (130), Category A (140)
        assert result[0].score == 150.0
        assert result[1].score == 130.0
        assert result[2].score == 140.0

    def test_handles_empty_list(self):
        """Verify empty list handled gracefully."""
        # Act
        result = content_formatter.group_by_category([])

        # Assert
        assert result == []

    def test_handles_single_category(self):
        """Verify single category handled correctly."""
        # Arrange
        candidates = [
            NewsletterCandidate(1, 10, "Post A", "http://a", "Summary A", "Author",
                                "Source", "Category A", datetime.now(), [], "Intermediate", 150.0),
            NewsletterCandidate(2, 10, "Post B", "http://b", "Summary B", "Author",
                                "Source", "Category A", datetime.now(), [], "Intermediate", 140.0),
        ]

        # Act
        result = content_formatter.group_by_category(candidates)

        # Assert
        assert len(result) == 2
        assert result[0].score == 150.0
        assert result[1].score == 140.0


class TestFormatNewsletterContent:
    """Tests for format_newsletter_content() function."""

    def test_includes_editorial_intro_placeholder(self, sample_candidates):
        """Verify editorial intro placeholder is present."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        assert "<!-- EDITORIAL INTRO: Operator adds context here in Beehiiv -->" in result

    def test_includes_editorial_commentary_placeholder(self, sample_candidates):
        """Verify editorial commentary placeholder is present."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        assert "<!-- EDITORIAL COMMENTARY: Operator adds wrap-up here in Beehiiv -->" in result

    def test_post_titles_are_clickable_links(self, sample_candidates):
        """Verify post titles formatted as markdown links."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        assert "[Understanding Event-Driven Architecture](https://example.com/event-driven-arch)" in result
        assert "[Kubernetes Best Practices for Production](https://example.com/k8s-best-practices)" in result

    def test_includes_all_required_fields(self, sample_candidates):
        """Verify all required fields present in formatted output."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        # Check for summary
        assert "**Summary:** This post explores event-driven patterns" in result

        # Check for source and author
        assert "**Source:** Engineering Blog | **Author:** Jane Smith" in result

        # Check for topics
        assert "**Topics:** #architecture, #events, #patterns" in result

        # Check for difficulty
        assert "**Difficulty:** Intermediate" in result

    def test_tags_formatted_as_hashtags(self, sample_candidates):
        """Verify tags formatted with # prefix."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        assert "#architecture" in result
        assert "#events" in result
        assert "#kubernetes" in result

    def test_horizontal_rules_separate_posts(self, sample_candidates):
        """Verify horizontal rules separate post entries."""
        # Act
        result = content_formatter.format_newsletter_content(sample_candidates)

        # Assert
        assert result.count("---") == 3  # One per post

    def test_handles_empty_list(self):
        """Verify empty list returns placeholders only."""
        # Act
        result = content_formatter.format_newsletter_content([])

        # Assert
        assert "<!-- EDITORIAL INTRO" in result
        assert "<!-- EDITORIAL COMMENTARY" in result
        assert "##" not in result  # No post headers

    def test_handles_posts_without_tags(self):
        """Verify posts without tags don't break formatting."""
        # Arrange
        candidate = NewsletterCandidate(
            1, 10, "Post Without Tags", "http://example.com", "Summary text",
            "Author", "Source", "Category", datetime.now(), [],
            "Beginner", 100.0
        )

        # Act
        result = content_formatter.format_newsletter_content([candidate])

        # Assert
        assert "Post Without Tags" in result
        assert "**Topics:**" not in result  # Should skip topics section if no tags
