"""Load active blog sources from the database.

Provides the source query used by the ingestion DAG.
"""

import logging

from src.common.db import get_connection
from src.common.models import BlogSource

logger = logging.getLogger(__name__)


def get_active_sources() -> list[BlogSource]:
    """Fetch all active blog sources from raw_blog_sources.

    Returns:
        List of BlogSource dataclass instances with status='active',
        ordered by id.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, rss_feed_url, name, category, quality_rating, "
                "status, last_checked_at, created_at, updated_at "
                "FROM raw_blog_sources WHERE status = 'active' ORDER BY id"
            )
            rows = cur.fetchall()

    sources = [
        BlogSource(
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
        for row in rows
    ]

    logger.info("Loaded %d active sources", len(sources))
    return sources
