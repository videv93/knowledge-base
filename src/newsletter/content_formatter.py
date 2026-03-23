"""Newsletter content formatter.

Assembles newsletter content from ranked candidate posts in mart_newsletter_candidates
into publish-ready markdown format with editorial placeholders for Beehiiv.

Architecture compliance:
- Reads ONLY from mart_newsletter_candidates (mart layer boundary enforced)
- Never accesses raw_blog_posts, stg_*, or any raw/staging table
- Passes typed NewsletterCandidate dataclasses (domain model boundary)
- Connection passed in by caller — use src.common.db.get_connection() at call site
- No Jinja2 templates — simple Python string assembly
- No HTTP calls — formatter produces string only (Beehiiv push is Story 4.3)
"""

import logging

from src.common.models import NewsletterCandidate

logger = logging.getLogger(__name__)


def fetch_candidates(conn) -> list[NewsletterCandidate]:
    """Fetch all newsletter candidates ordered by rank_score DESC.

    Queries mart_newsletter_candidates only (mart read boundary).

    Args:
        conn: Active database connection (obtain via src.common.db.get_connection())

    Returns:
        list[NewsletterCandidate]: Ranked candidates as typed dataclasses
    """
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    post_id, title, summary_text, tags,
                    difficulty_classification, author_name, source_name,
                    category, quality_rating, publication_date, url,
                    rank_score, category_rank
                FROM mart_newsletter_candidates
                ORDER BY rank_score DESC
            """)
            rows = cur.fetchall()
            candidates = [
                NewsletterCandidate(
                    post_id=row[0],
                    title=row[1],
                    summary_text=row[2],
                    tags=row[3] if row[3] is not None else [],
                    difficulty_classification=row[4],
                    author_name=row[5],
                    source_name=row[6],
                    category=row[7],
                    quality_rating=row[8],
                    publication_date=row[9],
                    url=row[10],
                    rank_score=row[11],
                    category_rank=row[12],
                )
                for row in rows
            ]
        logger.info("Fetched newsletter candidates", extra={"count": len(candidates)})
        return candidates
    except Exception:
        logger.error(
            "Failed to fetch newsletter candidates",
            extra={"table": "mart_newsletter_candidates"},
            exc_info=True,
        )
        raise


def group_by_category(
    candidates: list[NewsletterCandidate],
) -> dict[str, list[NewsletterCandidate]]:
    """Group candidates by category, preserving rank_score order within each category.

    Category order in the returned dict is alphabetical to ensure deterministic output.
    Within each category, posts preserve their original order (rank_score DESC from fetch).

    Args:
        candidates: List of NewsletterCandidate (typically pre-sorted by rank_score DESC)

    Returns:
        dict[str, list[NewsletterCandidate]]: category name → ranked post list
    """
    groups: dict[str, list[NewsletterCandidate]] = {}
    for candidate in candidates:
        category = candidate.category or "Uncategorized"
        if category not in groups:
            groups[category] = []
        groups[category].append(candidate)
    # Sort categories alphabetically for deterministic output
    return dict(sorted(groups.items()))


def format_post_entry(post: NewsletterCandidate) -> str:
    """Render a single post as a formatted newsletter section.

    Args:
        post: NewsletterCandidate dataclass instance

    Returns:
        str: Formatted markdown block for this post
    """
    title = post.title or "Untitled"
    url = post.url or "#missing-url"
    if not post.url:
        logger.warning("Post missing URL", extra={"title": title})
    source_name = post.source_name or "Unknown Source"
    author_name = post.author_name or "Unknown Author"
    summary = post.summary_text or "Summary unavailable."

    lines = [
        f"### [{title}]({url})",
        f"*{source_name} · {author_name}*",
        "",
        summary,
        "",
        f"[Read more]({url})",
    ]
    return "\n".join(lines)


def format_newsletter(candidates: list[NewsletterCandidate]) -> str:
    """Assemble complete newsletter body from all candidates.

    Structure:
    - Editorial intro placeholder
    - Category sections (alphabetical), each containing ranked posts
    - Editorial commentary placeholder

    Args:
        candidates: All NewsletterCandidate instances, grouped internally by category

    Returns:
        str: Complete formatted newsletter markdown string
    """
    lines = [
        "[EDITORIAL INTRO — Please add your intro here before publishing]",
        "",
        "---",
        "",
    ]

    grouped = group_by_category(candidates)

    for category, posts in grouped.items():
        lines.append(f"## {category}")
        lines.append("")
        for post in posts:
            lines.append(format_post_entry(post))
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("[EDITORIAL COMMENTARY — Add your commentary and closing thoughts here]")

    content = "\n".join(lines)
    logger.info("Formatted newsletter content", extra={"post_count": len(candidates)})
    return content


def generate_newsletter_content(conn) -> str:
    """Orchestrate fetch → group → format pipeline and return final newsletter string.

    Public entry point for newsletter content generation. Caller is responsible
    for providing an active connection (use src.common.db.get_connection() at call site).

    Args:
        conn: Active database connection

    Returns:
        str: Complete formatted newsletter markdown ready for Beehiiv operator review

    Raises:
        Exception: Re-raises any database or formatting errors after logging
    """
    try:
        candidates = fetch_candidates(conn)
        return format_newsletter(candidates)
    except Exception:
        logger.error("Failed to generate newsletter content", exc_info=True)
        raise


# Public API aliases — match names expected by src/newsletter/__init__.py
fetch_newsletter_candidates = fetch_candidates
format_newsletter_content = format_newsletter
