"""Tests for src.common.models module."""

from datetime import datetime, timezone

from src.common.models import BlogPost, BlogSource, DeadLetterEntry


def test_blog_source_creation():
    """BlogSource dataclass can be instantiated with all fields."""
    source = BlogSource(
        id=1,
        rss_feed_url="https://example.com/feed",
        name="Example Blog",
        category="Software Engineering",
        quality_rating=5,
        status="active",
    )
    assert source.id == 1
    assert source.rss_feed_url == "https://example.com/feed"
    assert source.name == "Example Blog"
    assert source.status == "active"


def test_blog_source_defaults():
    """BlogSource defaults status to 'active' and optional fields to None."""
    source = BlogSource(id=None, rss_feed_url="https://x.com/feed", name="X", category="DevOps", quality_rating=3)
    assert source.status == "active"
    assert source.last_checked_at is None
    assert source.created_at is None


def test_blog_post_creation():
    """BlogPost dataclass can be instantiated with all fields."""
    now = datetime.now(timezone.utc)
    post = BlogPost(
        id=1,
        source_id=10,
        title="Test Post",
        body="Post body content",
        url="https://example.com/post",
        publication_date=now,
        author_name="Author",
    )
    assert post.id == 1
    assert post.source_id == 10
    assert post.title == "Test Post"
    assert post.url == "https://example.com/post"


def test_dead_letter_entry_creation():
    """DeadLetterEntry dataclass can be instantiated with required fields."""
    entry = DeadLetterEntry(
        id=1,
        post_reference="https://example.com/post",
        failure_stage="ingestion",
        failure_reason="Connection timeout",
    )
    assert entry.id == 1
    assert entry.failure_stage == "ingestion"
    assert entry.retry_count == 0
    assert entry.last_retry_at is None
