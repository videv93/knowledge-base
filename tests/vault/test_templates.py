"""Tests for Jinja2 vault note templates and template renderer."""

import re

import pytest
import yaml

from src.vault.template_renderer import (
    render_author_note,
    render_post_note,
    render_source_note,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_post():
    return {
        "id": 42,
        "source_name": "Engineering at Meta",
        "author_name": "Jane Smith",
        "publication_date": "2026-02-15",
        "tags": ["distributed-systems", "scaling", "python"],
        "category": "Software Engineering",
        "url": "https://engineering.meta.com/post-42",
        "title": "Scaling Distributed Systems at Meta",
        "summary_text": "This post discusses scaling strategies used at Meta.",
    }


@pytest.fixture
def sample_source():
    return {
        "name": "Engineering at Meta",
        "category": "Software Engineering",
        "feed_url": "https://engineering.meta.com/feed",
        "total_post_count": 150,
        "status": "active",
        "latest_post_date": "2026-02-20",
    }


@pytest.fixture
def sample_author():
    return {
        "author_name": "Jane Smith",
        "primary_category": "Software Engineering",
        "post_count": 12,
        "first_seen_at": "2025-06-01",
        "last_seen_at": "2026-02-15",
    }


@pytest.fixture
def sample_posts_list():
    return [
        {"title": "Scaling Distributed Systems at Meta"},
        {"title": "Building Reliable Pipelines"},
    ]


@pytest.fixture
def sample_sources_list():
    return [
        {"name": "Engineering at Meta"},
        {"name": "Netflix Tech Blog"},
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_frontmatter(rendered: str) -> dict:
    """Extract and parse YAML frontmatter from rendered markdown."""
    match = re.match(r"^---\n(.*?)\n---", rendered, re.DOTALL)
    assert match, f"No YAML frontmatter found in:\n{rendered[:200]}"
    return yaml.safe_load(match.group(1))


def _find_wikilinks(text: str) -> list[str]:
    """Find all [[wikilink]] targets in text."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


# ---------------------------------------------------------------------------
# Post template tests (AC #1)
# ---------------------------------------------------------------------------


class TestPostTemplate:
    def test_renders_valid_yaml_frontmatter(self, sample_post):
        rendered = render_post_note(sample_post)
        fm = _extract_frontmatter(rendered)
        assert fm["uid"] == 42
        assert str(fm["date"]) == "2026-02-15"
        assert fm["category"] == "Software Engineering"
        assert fm["url"] == "https://engineering.meta.com/post-42"
        assert isinstance(fm["tags"], list)
        assert "distributed-systems" in fm["tags"]

    def test_frontmatter_wikilinks(self, sample_post):
        rendered = render_post_note(sample_post)
        fm = _extract_frontmatter(rendered)
        assert "[[Engineering at Meta]]" in fm["source"]
        assert "[[Jane Smith]]" in fm["author"]

    def test_body_has_ai_summary(self, sample_post):
        rendered = render_post_note(sample_post)
        assert "## AI Summary" in rendered
        assert "scaling strategies used at Meta" in rendered

    def test_body_has_topics_with_wikilinks(self, sample_post):
        rendered = render_post_note(sample_post)
        wikilinks = _find_wikilinks(rendered)
        assert "distributed-systems" in wikilinks
        assert "scaling" in wikilinks
        assert "python" in wikilinks

    def test_body_has_source_section(self, sample_post):
        rendered = render_post_note(sample_post)
        assert "## Source" in rendered
        assert "[[Engineering at Meta]]" in rendered
        assert "[[Jane Smith]]" in rendered
        assert "[Read Full Post](https://engineering.meta.com/post-42)" in rendered

    def test_template_variables_match_db_columns(self, sample_post):
        """Ensure template uses mart_posts column names exactly."""
        rendered = render_post_note(sample_post)
        # Should render without StrictUndefined errors
        assert "# Scaling Distributed Systems at Meta" in rendered

    def test_missing_summary(self, sample_post):
        sample_post["summary_text"] = None
        rendered = render_post_note(sample_post)
        assert "## AI Summary" in rendered
        assert "_No summary available yet._" in rendered

    def test_empty_tags(self, sample_post):
        sample_post["tags"] = []
        rendered = render_post_note(sample_post)
        fm = _extract_frontmatter(rendered)
        assert fm["tags"] == []
        assert "_No topics tagged yet._" in rendered

    def test_null_tags(self, sample_post):
        sample_post["tags"] = None
        rendered = render_post_note(sample_post)
        fm = _extract_frontmatter(rendered)
        # tags should be empty list in frontmatter
        assert fm["tags"] == []
        assert "_No topics tagged yet._" in rendered

    def test_null_author_shows_unknown(self, sample_post):
        sample_post["author_name"] = None
        rendered = render_post_note(sample_post)
        fm = _extract_frontmatter(rendered)
        assert "[[Unknown]]" in fm["author"]


# ---------------------------------------------------------------------------
# Source template tests (AC #2)
# ---------------------------------------------------------------------------


class TestSourceTemplate:
    def test_renders_valid_yaml_frontmatter(self, sample_source, sample_posts_list):
        rendered = render_source_note(sample_source, sample_posts_list)
        fm = _extract_frontmatter(rendered)
        assert fm["name"] == "Engineering at Meta"
        assert fm["category"] == "Software Engineering"
        assert fm["rss_url"] == "https://engineering.meta.com/feed"
        assert fm["total_post_count"] == 150
        assert fm["status"] == "active"

    def test_post_list_with_wikilinks(self, sample_source, sample_posts_list):
        rendered = render_source_note(sample_source, sample_posts_list)
        wikilinks = _find_wikilinks(rendered)
        assert "Scaling Distributed Systems at Meta" in wikilinks
        assert "Building Reliable Pipelines" in wikilinks

    def test_zero_posts(self, sample_source):
        rendered = render_source_note(sample_source, [])
        assert "_No posts from this source yet._" in rendered


# ---------------------------------------------------------------------------
# Author template tests (AC #3)
# ---------------------------------------------------------------------------


class TestAuthorTemplate:
    def test_renders_valid_yaml_frontmatter(
        self, sample_author, sample_posts_list, sample_sources_list
    ):
        rendered = render_author_note(
            sample_author, sample_posts_list, sample_sources_list
        )
        fm = _extract_frontmatter(rendered)
        assert fm["name"] == "Jane Smith"
        assert fm["primary_category"] == "Software Engineering"
        assert fm["post_count"] == 12

    def test_posts_with_wikilinks(
        self, sample_author, sample_posts_list, sample_sources_list
    ):
        rendered = render_author_note(
            sample_author, sample_posts_list, sample_sources_list
        )
        wikilinks = _find_wikilinks(rendered)
        assert "Scaling Distributed Systems at Meta" in wikilinks

    def test_sources_with_wikilinks(
        self, sample_author, sample_posts_list, sample_sources_list
    ):
        rendered = render_author_note(
            sample_author, sample_posts_list, sample_sources_list
        )
        wikilinks = _find_wikilinks(rendered)
        assert "Engineering at Meta" in wikilinks
        assert "Netflix Tech Blog" in wikilinks

    def test_single_source(self, sample_author, sample_posts_list):
        rendered = render_author_note(
            sample_author, sample_posts_list, [{"name": "Solo Blog"}]
        )
        wikilinks = _find_wikilinks(rendered)
        assert "Solo Blog" in wikilinks

    def test_zero_posts(self, sample_author, sample_sources_list):
        rendered = render_author_note(sample_author, [], sample_sources_list)
        assert "_No posts by this author yet._" in rendered

    def test_null_primary_category(
        self, sample_author, sample_posts_list, sample_sources_list
    ):
        sample_author["primary_category"] = None
        rendered = render_author_note(
            sample_author, sample_posts_list, sample_sources_list
        )
        fm = _extract_frontmatter(rendered)
        assert fm["primary_category"] == "Uncategorized"
