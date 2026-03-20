"""Source management operations for blog sources.

Add, deactivate, activate, update, and inspect blog sources
in raw_blog_sources.
"""

import logging
from datetime import datetime, timezone

import psycopg2

from src.common.db import get_connection
from src.common.models import BlogSource

logger = logging.getLogger(__name__)

UPDATABLE_FIELDS = {"rss_feed_url", "name", "category", "quality_rating"}


def add_source(rss_feed_url: str, name: str, category: str, quality_rating: int) -> dict:
    """Add a new blog source. Rejects duplicates by RSS URL.

    Returns:
        {"action": "inserted", "source_id": int} or
        {"action": "skipped", "reason": "duplicate"}
    """
    if not rss_feed_url or not rss_feed_url.strip():
        raise ValueError("rss_feed_url must not be empty")
    if not name or not name.strip():
        raise ValueError("name must not be empty")
    if not category or not category.strip():
        raise ValueError("category must not be empty")
    if not isinstance(quality_rating, int) or quality_rating < 1 or quality_rating > 10:
        raise ValueError("quality_rating must be an integer between 1 and 10")

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO raw_blog_sources (rss_feed_url, name, category, quality_rating, status, updated_at) "
                    "VALUES (%s, %s, %s, %s, 'active', NOW()) "
                    "ON CONFLICT (rss_feed_url) DO NOTHING "
                    "RETURNING id",
                    (rss_feed_url, name, category, quality_rating),
                )
                row = cur.fetchone()
    except psycopg2.Error:
        logger.error("Database error adding source: %s", rss_feed_url, exc_info=True)
        raise

    if row:
        logger.info("Inserted new source id=%d: %s", row[0], name)
        return {"action": "inserted", "source_id": row[0]}

    logger.info("Skipped duplicate source: %s", rss_feed_url)
    return {"action": "skipped", "reason": "duplicate"}


def deactivate_source(source_id: int) -> dict:
    """Set a source status to 'inactive'.

    Returns:
        {"action": "deactivated", "source_id": int} or
        {"action": "not_found", "source_id": int}
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE raw_blog_sources SET status = 'inactive', updated_at = NOW() WHERE id = %s",
                    (source_id,),
                )
                if cur.rowcount == 0:
                    logger.warning("Source id=%d not found for deactivation", source_id)
                    return {"action": "not_found", "source_id": source_id}
    except psycopg2.Error:
        logger.error("Database error deactivating source id=%d", source_id, exc_info=True)
        raise

    logger.info("Deactivated source id=%d", source_id)
    return {"action": "deactivated", "source_id": source_id}


def activate_source(source_id: int) -> dict:
    """Set a source status back to 'active'.

    Returns:
        {"action": "activated", "source_id": int} or
        {"action": "not_found", "source_id": int}
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE raw_blog_sources SET status = 'active', updated_at = NOW() WHERE id = %s",
                    (source_id,),
                )
                if cur.rowcount == 0:
                    logger.warning("Source id=%d not found for activation", source_id)
                    return {"action": "not_found", "source_id": source_id}
    except psycopg2.Error:
        logger.error("Database error activating source id=%d", source_id, exc_info=True)
        raise

    logger.info("Activated source id=%d", source_id)
    return {"action": "activated", "source_id": source_id}


def update_source(source_id: int, **kwargs) -> dict:
    """Update specified fields for a source. Only allowed fields accepted.

    Returns:
        {"action": "updated", "fields": list} or raises ValueError for invalid fields.
    """
    if not kwargs:
        raise ValueError("No fields provided to update")

    unknown = set(kwargs.keys()) - UPDATABLE_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {unknown}")

    for key, value in kwargs.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Empty value for field: {key}")
        if key == "quality_rating":
            if not isinstance(value, int) or value < 1 or value > 10:
                raise ValueError("quality_rating must be an integer between 1 and 10")

    # SECURITY: Field names are safe to interpolate because they are validated
    # against the UPDATABLE_FIELDS allowlist above. Do not remove the allowlist check.
    set_clauses = [f"{field} = %s" for field in kwargs]
    set_clauses.append("updated_at = NOW()")
    values = list(kwargs.values())
    values.append(source_id)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE raw_blog_sources SET {', '.join(set_clauses)} WHERE id = %s",
                    tuple(values),
                )
                if cur.rowcount == 0:
                    logger.warning("Source id=%d not found for update", source_id)
                    return {"action": "not_found", "source_id": source_id}
    except psycopg2.Error:
        logger.error("Database error updating source id=%d", source_id, exc_info=True)
        raise

    logger.info("Updated source id=%d, fields=%s", source_id, list(kwargs.keys()))
    return {"action": "updated", "fields": list(kwargs.keys())}


def get_source_by_id(source_id: int) -> BlogSource | None:
    """Fetch a single source by ID.

    Returns:
        BlogSource instance or None if not found.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, rss_feed_url, name, category, quality_rating, "
                "status, last_checked_at, created_at, updated_at "
                "FROM raw_blog_sources WHERE id = %s",
                (source_id,),
            )
            row = cur.fetchone()

    if row is None:
        return None

    return BlogSource(
        id=row[0],
        rss_feed_url=row[1],
        name=row[2],
        category=row[3],
        quality_rating=row[4],
        status=row[5],
        last_checked_at=row[6],
        created_at=row[7],
        updated_at=row[8],
    )


def get_source_health() -> list[dict]:
    """Return health metrics for all sources from mart_sources.

    Each dict contains: id, name, category, status, quality_rating,
    total_post_count, latest_post_date, last_checked_at, is_unhealthy (bool).

    Sources are flagged unhealthy if: status is not 'active', or
    total_post_count is 0 and source created >7 days ago, or
    last_checked_at is >3 days stale.
    """
    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, category, status, quality_rating, "
                "total_post_count, latest_post_date, last_checked_at, created_at "
                "FROM mart_sources ORDER BY id"
            )
            rows = cur.fetchall()

    results = []
    for row in rows:
        source_id = row[0]
        status = row[3]
        total_post_count = row[5]
        last_checked_at = row[7]
        created_at = row[8]

        is_unhealthy = False
        if status != "active":
            is_unhealthy = True
        elif total_post_count == 0 and created_at and (now - created_at).days > 7:
            is_unhealthy = True
        elif last_checked_at and (now - last_checked_at).days > 3:
            is_unhealthy = True

        results.append({
            "id": source_id,
            "name": row[1],
            "category": row[2],
            "status": status,
            "quality_rating": row[4],
            "total_post_count": total_post_count,
            "latest_post_date": row[6],
            "last_checked_at": last_checked_at,
            "is_unhealthy": is_unhealthy,
        })

    unhealthy_count = sum(1 for r in results if r["is_unhealthy"])
    if unhealthy_count:
        logger.warning("Found %d unhealthy sources out of %d total", unhealthy_count, len(results))
    else:
        logger.info("All %d sources are healthy", len(results))

    return results
