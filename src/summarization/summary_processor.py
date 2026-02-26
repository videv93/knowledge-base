"""Summary processing pipeline for batch blog post summarization.

Identifies unsummarized posts and processes them through the Claude client
with concurrency control and DLQ failure routing.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common.db import get_connection
from src.common.dlq import route_to_dlq
from src.common.models import AiSummary, BlogPost, ProcessingResult
from src.summarization.claude_client import ClaudeClient, SummarizationError

logger = logging.getLogger(__name__)


def get_unsummarized_posts() -> list[BlogPost]:
    """Query raw_blog_posts that have no corresponding raw_ai_summaries entry."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bp.id, bp.source_id, bp.title, bp.body, bp.url,
                       bp.publication_date, bp.author_name, bp.created_at
                FROM raw_blog_posts bp
                LEFT JOIN raw_ai_summaries ais ON bp.id = ais.post_id
                WHERE ais.id IS NULL
                ORDER BY bp.id
                """
            )
            rows = cur.fetchall()

    posts = [
        BlogPost(
            id=row[0],
            source_id=row[1],
            title=row[2],
            body=row[3],
            url=row[4],
            publication_date=row[5],
            author_name=row[6],
            created_at=row[7],
        )
        for row in rows
    ]
    logger.info("Found %d unsummarized posts", len(posts))
    return posts


def _store_summary(summary: AiSummary) -> bool:
    """Insert an AiSummary into raw_ai_summaries. Returns True if inserted, False if duplicate."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO raw_ai_summaries
                    (post_id, summary_text, tags, difficulty_classification, raw_api_response, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (post_id) DO NOTHING
                """,
                (
                    summary.post_id,
                    summary.summary_text,
                    json.dumps(summary.tags),
                    summary.difficulty_classification,
                    json.dumps(summary.raw_api_response) if summary.raw_api_response else None,
                ),
            )
            return cur.rowcount > 0


def summarize_post_and_store(client: ClaudeClient, post: BlogPost) -> str:
    """Summarize a single post and store the result.

    Returns:
        "succeeded" if summary was created and stored.
        "skipped" if post was already summarized (ON CONFLICT).
        "failed" if an error occurred (routed to DLQ). Never raises.
    """
    try:
        summary = client.summarize_post(
            title=post.title,
            body=post.body,
            post_id=post.id,
        )
        inserted = _store_summary(summary)
        if inserted:
            logger.info("Summarized post %d: %s", post.id, post.title[:60])
            return "succeeded"
        else:
            logger.info("Skipped post %d (already summarized): %s", post.id, post.title[:60])
            return "skipped"
    except SummarizationError as e:
        logger.warning("Summarization parse error for post %d: %s", post.id, e)
        route_to_dlq(
            post_reference=str(post.id),
            failure_stage="summarization",
            failure_reason=f"SummarizationError: {e}",
        )
        return "failed"
    except Exception as e:
        logger.warning("Summarization failed for post %d: %s", post.id, e)
        route_to_dlq(
            post_reference=str(post.id),
            failure_stage="summarization",
            failure_reason=f"{type(e).__name__}: {e}",
        )
        return "failed"


def process_all_unsummarized(max_concurrent: int | None = None) -> ProcessingResult:
    """Process all unsummarized posts with concurrency control.

    Args:
        max_concurrent: Max parallel API calls. Defaults to config.CLAUDE_CONCURRENCY.

    Returns:
        ProcessingResult with counts of total, succeeded, failed, skipped.
    """
    from src.common import config

    if max_concurrent is None:
        max_concurrent = config.CLAUDE_CONCURRENCY

    posts = get_unsummarized_posts()
    if not posts:
        logger.info("No unsummarized posts to process")
        return ProcessingResult(total_found=0, succeeded=0, failed=0, skipped=0)

    # ClaudeClient wraps anthropic.Anthropic which uses httpx — thread-safe per httpx docs.
    # Single client avoids per-thread connection overhead.
    client = ClaudeClient()
    succeeded = 0
    failed = 0
    skipped = 0

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(summarize_post_and_store, client, post): post
            for post in posts
        }
        for future in as_completed(futures):
            post = futures[future]
            try:
                outcome = future.result()
                if outcome == "succeeded":
                    succeeded += 1
                elif outcome == "skipped":
                    skipped += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error("Unexpected error processing post %d: %s", post.id, e)
                failed += 1

    result = ProcessingResult(
        total_found=len(posts),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
    )
    logger.info(
        "Processing complete: total=%d, succeeded=%d, failed=%d, skipped=%d",
        result.total_found,
        result.succeeded,
        result.failed,
        result.skipped,
    )
    return result
