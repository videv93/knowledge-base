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


def list_failures(
    failure_stage: Optional[str] = None,
    include_resolved: bool = False,
) -> list[DeadLetterEntry]:
    """Query dead letter queue entries, most recent first.

    Args:
        failure_stage: If provided, filter by this pipeline stage.
        include_resolved: If True, include resolved entries (default: only unresolved).

    Returns:
        List of DeadLetterEntry objects ordered by most recent first.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if failure_stage:
                cur.execute(
                    """
                    SELECT id, post_reference, failure_stage, failure_reason,
                           retry_count, created_at, last_retry_at, resolved
                    FROM dead_letter_posts
                    WHERE failure_stage = %s
                      AND (resolved = FALSE OR %s = TRUE)
                    ORDER BY created_at DESC
                    """,
                    (failure_stage, include_resolved),
                )
            else:
                cur.execute(
                    """
                    SELECT id, post_reference, failure_stage, failure_reason,
                           retry_count, created_at, last_retry_at, resolved
                    FROM dead_letter_posts
                    WHERE resolved = FALSE OR %s = TRUE
                    ORDER BY created_at DESC
                    """,
                    (include_resolved,),
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
            resolved=row[7],
        )
        for row in rows
    ]


def _load_entry(entry_id: int) -> DeadLetterEntry:
    """Load a single DLQ entry by ID. Raises ValueError if not found."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, post_reference, failure_stage, failure_reason,
                       retry_count, created_at, last_retry_at, resolved
                FROM dead_letter_posts
                WHERE id = %s
                """,
                (entry_id,),
            )
            row = cur.fetchone()

    if row is None:
        raise ValueError(f"DLQ entry {entry_id} not found")

    return DeadLetterEntry(
        id=row[0],
        post_reference=row[1],
        failure_stage=row[2],
        failure_reason=row[3],
        retry_count=row[4],
        created_at=row[5],
        last_retry_at=row[6],
        resolved=row[7],
    )


def _dispatch(entry: DeadLetterEntry) -> None:
    """Dispatch a DLQ entry to the appropriate pipeline stage for reprocessing.

    Deferred imports inside this function prevent circular dependencies —
    dlq.py is imported by all domain modules.

    Raises:
        ValueError: if failure_stage is unknown.
        LookupError: if the referenced post cannot be found.
        Exception: any exception from the downstream pipeline module.
    """
    stage = entry.failure_stage

    if stage == "summarization":
        from src.summarization.summary_processor import process_single_post
        process_single_post(int(entry.post_reference))

    elif stage == "ingestion":
        from src.ingestion.content_extractor import reingest_by_url
        reingest_by_url(entry.post_reference)

    elif stage == "generation":
        from src.vault.note_generator import generate_note_for_post
        generate_note_for_post(int(entry.post_reference))

    else:
        raise ValueError(f"Unknown failure_stage: {stage!r}")


def reprocess_entry(entry_id: int) -> None:
    """Re-submit a DLQ entry to the appropriate pipeline stage.

    On success: marks the entry resolved=TRUE, increments retry_count, updates last_retry_at.
    On failure: increments retry_count, updates failure_reason and last_retry_at. Re-raises.

    Args:
        entry_id: The DLQ entry ID to reprocess.

    Raises:
        ValueError: if entry_id not found or failure_stage unknown.
        Exception: propagated from the downstream pipeline module on reprocessing failure.
    """
    entry = _load_entry(entry_id)
    now = datetime.now(timezone.utc)

    try:
        _dispatch(entry)
    except Exception as e:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE dead_letter_posts
                    SET retry_count = retry_count + 1,
                        last_retry_at = %s,
                        failure_reason = %s
                    WHERE id = %s
                    """,
                    (now, str(e), entry_id),
                )
        logger.warning(
            "Reprocessing failed for DLQ entry %d (stage=%s): %s",
            entry_id,
            entry.failure_stage,
            e,
        )
        raise

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE dead_letter_posts
                SET resolved = TRUE,
                    retry_count = retry_count + 1,
                    last_retry_at = %s
                WHERE id = %s
                """,
                (now, entry_id),
            )
    logger.info(
        "DLQ entry %d resolved (stage=%s, reference=%s)",
        entry_id,
        entry.failure_stage,
        entry.post_reference,
    )


def reprocess_by_stage(stage_name: str) -> dict:
    """Batch-retry all unresolved DLQ entries for a given stage.

    Processes each entry independently — one failure does not abort the batch.

    Args:
        stage_name: Pipeline stage name to reprocess (ingestion, summarization, generation).

    Returns:
        dict with keys: attempted (int), succeeded (int), failed (int).
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, post_reference, failure_stage, failure_reason,
                       retry_count, created_at, last_retry_at, resolved
                FROM dead_letter_posts
                WHERE failure_stage = %s AND resolved = FALSE
                ORDER BY created_at ASC
                """,
                (stage_name,),
            )
            rows = cur.fetchall()

    entries = [
        DeadLetterEntry(
            id=row[0],
            post_reference=row[1],
            failure_stage=row[2],
            failure_reason=row[3],
            retry_count=row[4],
            created_at=row[5],
            last_retry_at=row[6],
            resolved=row[7],
        )
        for row in rows
    ]

    attempted = len(entries)
    succeeded = 0
    failed = 0

    for entry in entries:
        try:
            reprocess_entry(entry.id)
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.error(
                "reprocess_by_stage: entry %d failed (stage=%s): %s",
                entry.id,
                stage_name,
                e,
            )

    logger.info(
        "Reprocessed %d entries for stage '%s': %d succeeded, %d failed",
        attempted,
        stage_name,
        succeeded,
        failed,
    )
    return {"attempted": attempted, "succeeded": succeeded, "failed": failed}


def get_dlq_summary() -> dict:
    """Return count of unresolved DLQ entries grouped by failure stage.

    Returns:
        dict with keys:
            total_unresolved (int): total count of unresolved entries
            by_stage (dict[str, int]): counts keyed by failure_stage
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT failure_stage, COUNT(*)
                FROM dead_letter_posts
                WHERE resolved = FALSE
                GROUP BY failure_stage
                """
            )
            rows = cur.fetchall()

    by_stage = {row[0]: row[1] for row in rows}
    total = sum(by_stage.values())
    logger.info(
        "DLQ summary: %d unresolved entries — %s",
        total,
        by_stage if by_stage else "none",
    )
    return {"total_unresolved": total, "by_stage": by_stage}
