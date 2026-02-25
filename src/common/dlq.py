"""Dead letter queue interface for failure routing.

All failure routing across pipeline stages MUST go through this module.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.common.db import get_connection
from src.common.models import DeadLetterEntry

logger = logging.getLogger(__name__)


def route_to_dlq(post_reference: str, failure_stage: str, failure_reason: str) -> None:
    """Insert a failed item into the dead letter queue.

    Args:
        post_reference: Identifier for the failed post (URL or ID).
        failure_stage: Pipeline stage where failure occurred (ingestion, summarization, generation).
        failure_reason: Description of the failure.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO dead_letter_posts (post_reference, failure_stage, failure_reason, retry_count, created_at)
                VALUES (%s, %s, %s, 0, %s)
                """,
                (post_reference, failure_stage, failure_reason, datetime.now(timezone.utc)),
            )
    logger.error(
        "Routed to DLQ: stage=%s, reference=%s, reason=%s",
        failure_stage,
        post_reference,
        failure_reason,
    )


def list_failures(failure_stage: Optional[str] = None) -> list[DeadLetterEntry]:
    """Query dead letter queue entries, optionally filtered by stage.

    Args:
        failure_stage: If provided, filter by this pipeline stage.

    Returns:
        List of DeadLetterEntry objects ordered by most recent first.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if failure_stage:
                cur.execute(
                    """
                    SELECT id, post_reference, failure_stage, failure_reason, retry_count, created_at, last_retry_at
                    FROM dead_letter_posts
                    WHERE failure_stage = %s
                    ORDER BY created_at DESC
                    """,
                    (failure_stage,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, post_reference, failure_stage, failure_reason, retry_count, created_at, last_retry_at
                    FROM dead_letter_posts
                    ORDER BY created_at DESC
                    """
                )
            rows = cur.fetchall()

    return [
        DeadLetterEntry(
            id=row[0],
            post_reference=row[1],
            failure_stage=row[2],
            failure_reason=row[3],
            retry_count=row[4],
            created_at=row[5],
            last_retry_at=row[6],
        )
        for row in rows
    ]


def reprocess_entry(entry_id: int) -> None:
    """Re-submit a DLQ entry for processing. Stub — full implementation in Epic 6.

    Args:
        entry_id: The DLQ entry ID to reprocess.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE dead_letter_posts
                SET retry_count = retry_count + 1, last_retry_at = %s
                WHERE id = %s
                """,
                (datetime.now(timezone.utc), entry_id),
            )
    logger.info("DLQ entry %d marked for reprocessing", entry_id)
