"""Vault note generator — creates Obsidian markdown notes from mart table data.

This is the CANONICAL location for slug generation and note file writing.
No other module should generate slugs or write vault notes.

Reads from mart tables only (mart_posts, mart_authors, mart_sources).
"""

import hashlib
import logging
import os
import tempfile
from collections import defaultdict
from pathlib import Path

from slugify import slugify

from src.vault.template_renderer import render_author_note, render_post_note, render_source_note

logger = logging.getLogger(__name__)


def slugify_title(title: str, max_length: int = 80) -> str:
    """Generate a deterministic, filesystem-safe slug from a title.

    Uses python-slugify truncated to max_length chars.
    """
    if not title:
        return "untitled"
    return slugify(title, max_length=max_length)


def slugify_with_hash(title: str, max_length: int = 80) -> str:
    """Generate a slug with a 6-char hash suffix for guaranteed uniqueness.

    Total length stays within max_length (base truncated to max_length - 7 to fit '-' + 6 hex chars).
    """
    hash_suffix = hashlib.md5(title.encode()).hexdigest()[:6]
    base = slugify(title, max_length=max(max_length - 7, 1))
    if not base:
        return hash_suffix
    return f"{base}-{hash_suffix}"


def _write_note(path: Path, content: str) -> None:
    """Write note content to path atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def generate_post_notes(posts: list[dict], output_dir: Path) -> list[Path]:
    """Generate post notes into output_dir/posts/{category}/{slug}.md.

    Returns list of paths written. Assigns 'post_slug' to each post dict
    as a side effect for downstream wikilink resolution.
    """
    written = []
    slug_counts: dict[str, int] = defaultdict(int)

    # First pass: compute slugs and detect collisions
    slugs = []
    for post in posts:
        base_slug = slugify_title(post.get("title", ""))
        slugs.append(base_slug)
        slug_counts[base_slug] += 1

    for post, base_slug in zip(posts, slugs):
        try:
            # Use hash suffix if collision detected
            if slug_counts[base_slug] > 1:
                file_slug = slugify_with_hash(post.get("title", ""))
            else:
                file_slug = base_slug

            category_slug = slugify_title(post.get("category", "uncategorized"))
            note_path = output_dir / "posts" / category_slug / f"{file_slug}.md"

            content = render_post_note(post)
            _write_note(note_path, content)
            written.append(note_path)

            # Store slug on the dict for wikilink resolution
            post["_file_slug"] = file_slug

            logger.info(
                "Generated post note: %s",
                note_path.relative_to(output_dir),
                extra={"title": post.get("title"), "category": category_slug},
            )
        except Exception:
            logger.error(
                "Failed to generate post note for '%s'",
                post.get("title", "unknown"),
                exc_info=True,
            )

    return written


def generate_source_notes(sources: list[dict], posts_by_source: dict[int, list[dict]], output_dir: Path) -> list[Path]:
    """Generate source notes into output_dir/sources/{slug}.md."""
    written = []
    for source in sources:
        try:
            name = source.get("name", "")
            file_slug = slugify_title(name)
            note_path = output_dir / "sources" / f"{file_slug}.md"

            source_posts = posts_by_source.get(source.get("id"), [])
            content = render_source_note(source, source_posts)
            _write_note(note_path, content)
            written.append(note_path)

            logger.info(
                "Generated source note: %s",
                note_path.relative_to(output_dir),
                extra={"source": name},
            )
        except Exception:
            logger.error(
                "Failed to generate source note for '%s'",
                source.get("name", "unknown"),
                exc_info=True,
            )

    return written


def generate_author_notes(
    authors: list[dict],
    posts_by_author: dict[int, list[dict]],
    sources_by_author: dict[int, list[dict]],
    output_dir: Path,
) -> list[Path]:
    """Generate author notes into output_dir/authors/{slug}.md.

    Skips authors with NULL/empty author_name.
    """
    written = []
    for author in authors:
        try:
            name = author.get("author_name")
            if not name:
                logger.warning("Skipping author with NULL/empty name (id=%s)", author.get("author_id"))
                continue

            file_slug = slugify_title(name)
            note_path = output_dir / "authors" / f"{file_slug}.md"

            author_id = author.get("author_id")
            author_posts = posts_by_author.get(author_id, [])
            author_sources = sources_by_author.get(author_id, [])

            content = render_author_note(author, author_posts, author_sources)
            _write_note(note_path, content)
            written.append(note_path)

            logger.info(
                "Generated author note: %s",
                note_path.relative_to(output_dir),
                extra={"author": name},
            )
        except Exception:
            logger.error(
                "Failed to generate author note for '%s'",
                author.get("author_name", "unknown"),
                exc_info=True,
            )

    return written


def fetch_all_posts() -> list[dict]:
    """Fetch all posts from mart_posts."""
    from src.common import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_id, source_name, category, title, url,
                       author_name, author_id, publication_date, summary_text,
                       tags, difficulty_classification
                FROM mart_posts
                ORDER BY publication_date DESC
                """
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def fetch_all_sources() -> list[dict]:
    """Fetch all sources from mart_sources."""
    from src.common import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, category, rss_feed_url, status,
                       last_checked_at, total_post_count, latest_post_date
                FROM mart_sources
                ORDER BY name
                """
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def fetch_all_authors() -> list[dict]:
    """Fetch all authors from mart_authors."""
    from src.common import db

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT author_id, author_name, post_count, source_ids,
                       first_seen_at, last_seen_at, primary_category
                FROM mart_authors
                ORDER BY author_name
                """
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def _group_posts_by(posts: list[dict], key: str) -> dict:
    """Group posts by a given key into a dict of lists."""
    grouped: dict = defaultdict(list)
    for post in posts:
        val = post.get(key)
        if val is not None:
            grouped[val].append(post)
    return dict(grouped)


def _build_sources_by_author(posts: list[dict], sources: list[dict]) -> dict[int, list[dict]]:
    """Build a mapping from author_id to list of source dicts they write for."""
    source_lookup = {s["id"]: s for s in sources}
    author_source_ids: dict[int, set] = defaultdict(set)

    for post in posts:
        author_id = post.get("author_id")
        source_id = post.get("source_id")
        if author_id is not None and source_id is not None:
            author_source_ids[author_id].add(source_id)

    return {
        author_id: [source_lookup[sid] for sid in sids if sid in source_lookup]
        for author_id, sids in author_source_ids.items()
    }


def generate_all(output_dir: Path) -> dict:
    """Orchestrate full vault note generation from mart tables.

    Queries all mart data, groups it, generates all note types.
    Returns summary stats dict.
    """
    logger.info("Starting vault note generation to %s", output_dir)

    posts = fetch_all_posts()
    sources = fetch_all_sources()
    authors = fetch_all_authors()

    logger.info("Loaded %d posts, %d sources, %d authors from mart tables", len(posts), len(sources), len(authors))

    posts_by_source = _group_posts_by(posts, "source_id")
    posts_by_author = _group_posts_by(posts, "author_id")
    sources_by_author = _build_sources_by_author(posts, sources)

    post_paths = generate_post_notes(posts, output_dir)
    source_paths = generate_source_notes(sources, posts_by_source, output_dir)
    author_paths = generate_author_notes(authors, posts_by_author, sources_by_author, output_dir)

    stats = {
        "posts_generated": len(post_paths),
        "sources_generated": len(source_paths),
        "authors_generated": len(author_paths),
        "total_notes": len(post_paths) + len(source_paths) + len(author_paths),
    }

    logger.info(
        "Vault generation complete: %d posts, %d sources, %d authors (%d total)",
        stats["posts_generated"],
        stats["sources_generated"],
        stats["authors_generated"],
        stats["total_notes"],
    )

    return stats
