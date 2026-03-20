"""Newsletter generation module.

Assembles ranked candidate posts into publish-ready markdown for Beehiiv,
and publishes drafts via the Beehiiv API.

Beehiiv client imports are deferred to avoid requiring httpx/markdown at
import time — only code that actually creates drafts pays that cost.
"""

from src.newsletter.content_formatter import (
    fetch_newsletter_candidates,
    format_newsletter_content,
    group_by_category,
)


def __getattr__(name: str):
    """Lazy-load BeehiivClient and BeehiivApiError to avoid import-time deps."""
    if name in ("BeehiivClient", "BeehiivApiError"):
        from src.newsletter.beehiiv_client import BeehiivApiError, BeehiivClient

        _lazy = {"BeehiivClient": BeehiivClient, "BeehiivApiError": BeehiivApiError}
        return _lazy[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BeehiivApiError",
    "BeehiivClient",
    "fetch_newsletter_candidates",
    "format_newsletter_content",
    "group_by_category",
]
