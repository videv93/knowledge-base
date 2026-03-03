"""Newsletter content formatter.

Assembles newsletter content from ranked candidate posts into publish-ready markdown
format with editorial placeholders for Beehiiv.
"""

import logging
from collections import defaultdict

from src.common import db
from src.common.models import NewsletterCandidate

logger = logging.getLogger(__name__)


def fetch_newsletter_candidates() -> list[NewsletterCandidate]:
    """Fetch ranked newsletter candidate posts from database.

    Queries the mart_newsletter_candidates table and returns a list of
    NewsletterCandidate objects ordered by score descending.

    Returns:
        list[NewsletterCandidate]: Ranked candidates (up to 20 posts)
    """
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        id, source_id, title, url, summary_text,
                        author_name, source_name, category, publication_date,
                        tags, difficulty_classification, score
                    FROM mart_newsletter_candidates
                    ORDER BY score DESC
                """)
                rows = cur.fetchall()

                candidates = []
                for row in rows:
                    candidate = NewsletterCandidate(
                        id=row[0],
                        source_id=row[1],
                        title=row[2],
                        url=row[3],
                        summary_text=row[4],
                        author_name=row[5],
                        source_name=row[6],
                        category=row[7],
                        publication_date=row[8],
                        tags=row[9] if row[9] else [],  # Handle NULL JSONB
                        difficulty_classification=row[10],
                        score=row[11]
                    )
                    candidates.append(candidate)

                logger.info("Fetched newsletter candidates", extra={"count": len(candidates)})
                return candidates

    except Exception as e:
        logger.error("Failed to fetch newsletter candidates", extra={"error": str(e)})
        raise


def group_by_category(candidates: list[NewsletterCandidate]) -> list[NewsletterCandidate]:
    """Group posts by category and interleave for topic diversity.

    Ensures newsletter doesn't front-load one category by interleaving
    categories in round-robin fashion while preserving score order within
    each category.

    Args:
        candidates: List of newsletter candidates (typically pre-sorted by score)

    Returns:
        list[NewsletterCandidate]: Candidates reordered for category diversity
    """
    if not candidates:
        return []

    # Group by category, preserving score order within category
    by_category = defaultdict(list)
    for candidate in candidates:
        by_category[candidate.category].append(candidate)

    # Interleave categories round-robin
    result = []
    categories = list(by_category.keys())
    max_len = max(len(posts) for posts in by_category.values()) if by_category else 0

    for i in range(max_len):
        for category in categories:
            if i < len(by_category[category]):
                result.append(by_category[category][i])

    logger.debug("Grouped candidates by category", extra={
        "total_candidates": len(candidates),
        "categories": len(categories),
        "result_count": len(result)
    })

    return result


def format_newsletter_content(candidates: list[NewsletterCandidate]) -> str:
    """Format newsletter candidates into publish-ready markdown.

    Generates newsletter content with editorial placeholders, post entries with
    AI summaries and metadata, following the Beehiiv-compatible markdown format.

    Args:
        candidates: List of newsletter candidates (should be diversity-ordered)

    Returns:
        str: Formatted markdown newsletter content
    """
    lines = []

    # Editorial intro placeholder
    lines.append("<!-- EDITORIAL INTRO: Operator adds context here in Beehiiv -->")
    lines.append("")

    # Post entries
    for candidate in candidates:
        # Title as markdown link
        lines.append(f"## [{candidate.title}]({candidate.url})")
        lines.append("")

        # AI Summary
        lines.append(f"**Summary:** {candidate.summary_text}")
        lines.append("")

        # Source and Author on same line
        lines.append(f"**Source:** {candidate.source_name} | **Author:** {candidate.author_name}")
        lines.append("")

        # Topics as hashtags
        if candidate.tags:
            tags_str = ", ".join(f"#{tag}" for tag in candidate.tags)
            lines.append(f"**Topics:** {tags_str}")
            lines.append("")

        # Difficulty classification
        lines.append(f"**Difficulty:** {candidate.difficulty_classification}")
        lines.append("")

        # Horizontal rule separator
        lines.append("---")
        lines.append("")

    # Editorial commentary placeholder
    lines.append("<!-- EDITORIAL COMMENTARY: Operator adds wrap-up here in Beehiiv -->")

    content = "\n".join(lines)

    logger.info("Formatted newsletter content", extra={"post_count": len(candidates)})

    return content
