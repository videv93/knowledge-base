"""RSS feed parser using feedparser.

Parses RSS 2.0, Atom, and JSON Feed formats. Extracts post entries
with normalized fields for database ingestion.
"""

import logging
from calendar import timegm
from datetime import datetime, timedelta, timezone

import feedparser

from src.common import dlq
from src.common.models import BlogSource

logger = logging.getLogger(__name__)


def parse_feed(source: BlogSource) -> list[dict]:
    """Parse an RSS feed and return normalized post entries.

    Args:
        source: BlogSource with rss_feed_url to parse.

    Returns:
        List of dicts with keys: title, body, url, publication_date, author_name.
        Empty list on complete failure.
    """
    try:
        feed = feedparser.parse(source.rss_feed_url)
    except Exception as e:
        logger.warning("Feed fetch failed for %s (%s): %s", source.name, source.rss_feed_url, e)
        dlq.route_to_dlq(source.rss_feed_url, "ingestion", f"Feed fetch failed: {e}")
        return []

    if feed.bozo:
        logger.warning(
            "Feed parse issue for %s (%s): %s",
            source.name,
            source.rss_feed_url,
            feed.bozo_exception,
        )
        if not feed.entries:
            dlq.route_to_dlq(
                source.rss_feed_url,
                "ingestion",
                f"Feed parse failed with no entries: {feed.bozo_exception}",
            )
            return []

    entries = []
    for entry in feed.entries:
        title = entry.get("title", "")
        url = entry.get("link", "")

        if not url or not title:
            logger.warning(
                "Skipping entry missing url or title in %s: title=%r, url=%r",
                source.name,
                title,
                url,
            )
            continue

        body = _extract_body(entry)
        author_name = _extract_author(entry)
        publication_date = _extract_date(entry)

        entries.append({
            "title": title,
            "body": body,
            "url": url,
            "publication_date": publication_date,
            "author_name": author_name,
        })

    logger.info("Parsed %d entries from %s", len(entries), source.name)
    return entries


def filter_entries_by_date(entries: list[dict], max_age_days: int = 30) -> list[dict]:
    """Filter parsed feed entries to only include posts within max_age_days.

    Args:
        entries: List of entry dicts from parse_feed().
        max_age_days: Maximum age in days. Entries older than this are skipped.

    Returns:
        Filtered list. Entries with publication_date=None are INCLUDED (age unknown).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    filtered = []
    skipped = 0
    for entry in entries:
        pub_date = entry.get("publication_date")
        if pub_date is not None and pub_date < cutoff:
            skipped += 1
            continue
        filtered.append(entry)
    if skipped > 0:
        logger.info("Filtered out %d entries older than %d days", skipped, max_age_days)
    return filtered


def _extract_body(entry) -> str:
    """Extract body content with fallback chain: content → summary → description → empty."""
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].value
    if hasattr(entry, "summary") and entry.summary:
        return entry.summary
    if hasattr(entry, "description") and entry.description:
        return entry.description
    return ""


def _extract_author(entry) -> str:
    """Extract author with fallback: author → author_detail.name → 'Unknown'."""
    author = entry.get("author", "")
    if not author and hasattr(entry, "author_detail"):
        author = entry.author_detail.get("name", "")
    return author or "Unknown"


def _extract_date(entry) -> datetime | None:
    """Extract publication date from time struct to UTC datetime."""
    time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if time_struct:
        return datetime.fromtimestamp(timegm(time_struct), tz=timezone.utc)
    return None
