"""Single entry point for all Beehiiv API operations.

Reads credentials from config at call time for zero-downtime key rotation.
Drafts are always pushed with status="draft" — never "confirmed" to prevent
accidental newsletter sends to subscribers.

Architecture compliance:
- Single entry point: only module allowed to call the Beehiiv API
- Credentials read from src.common.config at call time (supports key rotation without restart)
- Retry on 429/5xx via src.common.retry.retry_with_backoff
- Immediate raise on 4xx (excluding 429) — no retry for client errors
"""

import logging

import markdown as md
import requests

from src.common.retry import retry_with_backoff

logger = logging.getLogger(__name__)

BEEHIIV_API_BASE = "https://api.beehiiv.com/v2"


class BeehiivAPIError(Exception):
    """Non-retryable Beehiiv API error (4xx excluding 429)."""


class BeehiivRetryableError(Exception):
    """Retryable Beehiiv API error (429 rate limit or 5xx server error)."""


def _markdown_to_html(content: str) -> str:
    """Convert markdown newsletter content to HTML for Beehiiv body_content field.

    Args:
        content: Markdown string (e.g. output of content_formatter.generate_newsletter_content)

    Returns:
        str: HTML string suitable for Beehiiv body_content field
    """
    return md.markdown(content, extensions=["extra"])


@retry_with_backoff(exceptions=(BeehiivRetryableError,))
def _post_draft(url: str, payload: dict) -> dict:
    """Make a single POST attempt to the Beehiiv API.

    Reads credentials from config on every call so each retry attempt picks up
    any key rotation that occurred since the previous attempt.

    Separated from push_draft so retry_with_backoff decorator only wraps the HTTP call.

    Raises:
        BeehiivRetryableError: On HTTP 429 or 5xx — will be retried by decorator
        BeehiivAPIError: On HTTP 4xx (excluding 429) — raised immediately, no retry
    """
    from src.common import config  # read fresh on every attempt for key rotation support

    headers = {
        "Authorization": f"Bearer {config.BEEHIIV_API_KEY}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)

    if 200 <= response.status_code < 300:
        return response.json()

    if response.status_code == 429 or response.status_code >= 500:
        logger.error(
            "Beehiiv API retryable error: url=%s status=%d body=%.500s",
            url,
            response.status_code,
            response.text,
        )
        raise BeehiivRetryableError(
            f"Beehiiv API returned {response.status_code}: {response.text[:500]}"
        )

    # 4xx (non-429): client error — raise immediately without retry
    logger.error(
        "Beehiiv API client error: url=%s status=%d body=%.500s",
        url,
        response.status_code,
        response.text,
    )
    raise BeehiivAPIError(
        f"Beehiiv API returned {response.status_code}: {response.text[:500]}"
    )


def push_draft(title: str, body_content: str) -> str:
    """Push newsletter as a draft to Beehiiv.

    Reads BEEHIIV_API_KEY and BEEHIIV_PUBLICATION_ID from config at call time,
    enabling zero-downtime key rotation — update the env var and the next call
    uses the new key without any code changes or pipeline restart.

    Args:
        title: Newsletter subject/heading shown in Beehiiv UI
        body_content: Markdown string from content_formatter.generate_newsletter_content()
                      (converted to HTML internally before sending to Beehiiv)

    Returns:
        str: Beehiiv post ID (e.g. "post_abc123") for the created draft

    Raises:
        BeehiivAPIError: Non-retryable 4xx API failure
        BeehiivRetryableError: All retries exhausted on 429/5xx failure
    """
    from src.common import config  # lazy import — avoids triggering config validation at module load

    pub_id = config.BEEHIIV_PUBLICATION_ID
    url = f"{BEEHIIV_API_BASE}/publications/{pub_id}/posts"
    payload = {
        "title": title,
        "body_content": _markdown_to_html(body_content),
        "status": "draft",
    }

    response_data = _post_draft(url, payload)
    post_id = response_data["data"]["id"]
    logger.info("Created Beehiiv draft: post_id=%s title=%s", post_id, title)
    return post_id
