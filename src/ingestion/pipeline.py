"""Ingestion pipeline orchestrator.

Coordinates RSS parsing and post ingestion across all sources.
This is the entry point called by the Airflow DAG.
"""

import logging
from datetime import datetime, timezone

from src.common.db import get_connection
from src.common.models import BlogSource
from src.ingestion.content_extractor import ingest_posts
from src.ingestion.rss_parser import parse_feed

logger = logging.getLogger(__name__)


def run_ingestion(sources: list[BlogSource]) -> dict:
    """Run the full ingestion pipeline for all provided sources.

    Args:
        sources: List of BlogSource objects to process.

    Returns:
        Aggregate metrics dict with keys: total_success, total_duplicates,
        total_failures, sources_processed, sources_failed.
    """
    total_success = 0
    total_duplicates = 0
    total_failures = 0
    sources_processed = 0
    sources_failed = 0

    for source in sources:
        try:
            entries = parse_feed(source)
            if entries:
                metrics = ingest_posts(source, entries)
                total_success += metrics["success_count"]
                total_duplicates += metrics["duplicate_count"]
                total_failures += metrics["failure_count"]
            _update_last_checked(source.id)
            sources_processed += 1
        except Exception as e:
            sources_failed += 1
            logger.error("Source %s failed: %s", source.name, e)

    logger.info(
        "Ingestion complete: %d sources processed, %d failed, %d posts inserted, %d duplicates, %d failures",
        sources_processed,
        sources_failed,
        total_success,
        total_duplicates,
        total_failures,
    )

    return {
        "total_success": total_success,
        "total_duplicates": total_duplicates,
        "total_failures": total_failures,
        "sources_processed": sources_processed,
        "sources_failed": sources_failed,
    }


def _update_last_checked(source_id: int) -> None:
    """Update raw_blog_sources.last_checked_at for the given source."""
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE raw_blog_sources SET last_checked_at = %s, updated_at = %s WHERE id = %s",
                (now, now, source_id),
            )
