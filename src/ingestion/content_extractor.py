"""Content extraction and database ingestion for parsed RSS entries.

Inserts parsed post entries into raw_blog_posts with deduplication
via ON CONFLICT (url) DO NOTHING.
"""

import logging
from datetime import datetime, timezone

import psycopg2

from src.common import dlq
from src.common.db import get_connection
from src.common.models import BlogSource

logger = logging.getLogger(__name__)

INSERT_POST_SQL = """
    INSERT INTO raw_blog_posts (source_id, title, body, url, publication_date, author_name, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (url) DO NOTHING
"""


def ingest_posts(source: BlogSource, entries: list[dict]) -> dict:
    """Insert parsed entries into raw_blog_posts.

    Args:
        source: BlogSource providing source_id.
        entries: List of dicts with keys: title, body, url, publication_date, author_name.

    Returns:
        Metrics dict: {"success_count": int, "duplicate_count": int, "failure_count": int}
    """
    success_count = 0
    duplicate_count = 0
    failure_count = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            for entry in entries:
                try:
                    cur.execute("SAVEPOINT entry_sp")
                    cur.execute(INSERT_POST_SQL, (
                        source.id,
                        entry["title"],
                        entry["body"],
                        entry["url"],
                        entry["publication_date"],
                        entry["author_name"],
                        datetime.now(timezone.utc),
                    ))
                    cur.execute("RELEASE SAVEPOINT entry_sp")
                    if cur.rowcount == 1:
                        success_count += 1
                    else:
                        duplicate_count += 1
                except psycopg2.Error as e:
                    cur.execute("ROLLBACK TO SAVEPOINT entry_sp")
                    failure_count += 1
                    logger.warning(
                        "Failed to ingest post %s from %s: %s",
                        entry.get("url", "unknown"),
                        source.name,
                        e,
                    )
                    try:
                        dlq.route_to_dlq(
                            entry.get("url", "unknown"),
                            "ingestion",
                            f"Insert failed for source {source.name}: {e}",
                        )
                    except Exception as dlq_err:
                        logger.error("DLQ routing also failed for %s: %s", entry.get("url", "unknown"), dlq_err)

    logger.info(
        "Ingestion metrics for %s: %d inserted, %d duplicates, %d failures",
        source.name,
        success_count,
        duplicate_count,
        failure_count,
    )

    return {
        "success_count": success_count,
        "duplicate_count": duplicate_count,
        "failure_count": failure_count,
    }


def reingest_by_url(url: str) -> None:
    """Attempt to reprocess a DLQ ingestion failure for the given post URL.

    MVP implementation: checks if the post already exists in raw_blog_posts.
    If found, the original ingestion succeeded (DLQ entry is a false positive) —
    logs INFO and returns normally so reprocess_entry can mark it resolved.
    If not found, raw RSS data is gone and cannot be re-ingested without a live
    feed — raises LookupError so reprocess_entry records the failure.

    Args:
        url: The post URL from the DLQ entry's post_reference field.

    Raises:
        LookupError: if the post is not in raw_blog_posts (cannot re-ingest).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM raw_blog_posts WHERE url = %s LIMIT 1",
                (url,),
            )
            row = cur.fetchone()

    if row is not None:
        logger.info(
            "Post %s found in raw_blog_posts — ingestion succeeded, marking resolved",
            url,
        )
        return

    logger.warning(
        "Post %s not found in raw_blog_posts — raw RSS data gone, cannot re-ingest",
        url,
    )
    raise LookupError(f"Post not found in raw_blog_posts for URL: {url}")
