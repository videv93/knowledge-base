"""Template renderer for Obsidian vault note generation.

Loads Jinja2 templates from the templates/ directory and renders
post, source, and author notes from mart table data.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Templates directory at project root
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _get_env() -> Environment:
    """Create Jinja2 environment configured for vault note rendering."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def render_post_note(post: dict) -> str:
    """Render a post note from mart_posts row data.

    Args:
        post: Dict with keys matching mart_posts columns:
              id, source_name, author_name, publication_date, tags,
              category, url, title, summary_text
    """
    env = _get_env()
    template = env.get_template("post_note.md.j2")
    return template.render(post=post)


def render_source_note(source: dict, posts: list[dict]) -> str:
    """Render a source note from mart_sources row data.

    Args:
        source: Dict with keys matching mart_sources columns:
                name, category, feed_url, total_post_count, status, latest_post_date
        posts: List of post dicts (each with at least 'title' key)
    """
    env = _get_env()
    template = env.get_template("source_note.md.j2")
    return template.render(source=source, posts=posts)


def render_author_note(author: dict, posts: list[dict], sources: list[dict]) -> str:
    """Render an author note from mart_authors row data.

    Args:
        author: Dict with keys matching mart_authors columns:
                author_name, primary_category, post_count, first_seen_at, last_seen_at
        posts: List of post dicts (each with at least 'title' key)
        sources: List of source dicts (each with at least 'name' key)
    """
    env = _get_env()
    template = env.get_template("author_note.md.j2")
    return template.render(author=author, posts=posts, sources=sources)
