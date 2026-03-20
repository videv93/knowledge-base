"""Beehiiv API client for newsletter draft publishing.

Single entry point for all Beehiiv API operations.
Pushes formatted newsletter content as drafts to Beehiiv for operator review.
"""

import logging
import time

import httpx
import markdown

logger = logging.getLogger(__name__)

BASE_URL = "https://api.beehiiv.com/v2"
DEFAULT_TIMEOUT = 30  # seconds


class BeehiivApiError(Exception):
    """Raised when a Beehiiv API call fails in a non-retryable way."""

    def __init__(self, message: str, status_code: int | None = None, response_body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class BeehiivClient:
    """Client for Beehiiv newsletter API.

    Reads API credentials fresh on each call to support key rotation
    without pipeline downtime (NFR9).
    """

    def __init__(self):
        self.base_url = BASE_URL

    def _get_headers(self) -> dict:
        """Build request headers with fresh API key from config.

        Reads BEEHIIV_API_KEY on every call so the operator can rotate
        keys without restarting the pipeline.
        """
        from src.common import config

        if not config.BEEHIIV_API_KEY:
            raise BeehiivApiError("BEEHIIV_API_KEY is not configured. Set it in your .env file or environment.")
        return {
            "Authorization": f"Bearer {config.BEEHIIV_API_KEY}",
            "Content-Type": "application/json",
        }

    def _get_publication_id(self) -> str:
        """Read publication ID fresh from config."""
        from src.common import config

        if not config.BEEHIIV_PUBLICATION_ID:
            raise BeehiivApiError(
                "BEEHIIV_PUBLICATION_ID is not configured. Set it in your .env file or environment."
            )
        return config.BEEHIIV_PUBLICATION_ID

    def _markdown_to_html(self, md_content: str) -> str:
        """Convert markdown content to HTML for Beehiiv API.

        Beehiiv requires HTML in the body_content field; it does not
        accept raw markdown.
        """
        return markdown.markdown(md_content, extensions=["extra"])

    def create_draft(self, title: str, content: str) -> dict:
        """Create a newsletter draft in Beehiiv.

        Converts markdown content to HTML, then pushes to Beehiiv API
        as a draft post. The operator reviews and publishes in Beehiiv UI.

        Args:
            title: Newsletter issue title (e.g., "Weekly Knowledge Digest - 2026-03-20").
            content: Formatted markdown content from content_formatter.

        Returns:
            Dict with draft details: {"id": str, "status": "draft"}.

        Raises:
            BeehiivApiError: On non-retryable API errors (4xx except 429).
        """
        publication_id = self._get_publication_id()
        url = f"{self.base_url}/publications/{publication_id}/posts"
        headers = self._get_headers()

        html_content = self._markdown_to_html(content)

        payload = {
            "title": title,
            "body_content": html_content,
            "status": "draft",
        }

        logger.debug("Creating Beehiiv draft: %s", title[:80])

        return self._post_with_retry(url, headers, payload)

    def _post_with_retry(self, url: str, headers: dict, payload: dict) -> dict:
        """POST to Beehiiv API with retry on 429/5xx errors.

        Implements retry with exponential backoff matching architecture
        standard: 3 attempts at 30s, 120s, 480s intervals.

        Non-retryable errors (4xx except 429) raise immediately.
        """
        max_retries = 3
        base_delay = 30

        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                response = httpx.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

                if response.status_code == 201:
                    data = response.json()
                    draft_id = data.get("data", {}).get("id", "unknown")
                    logger.info(
                        "Draft created successfully",
                        extra={"draft_id": draft_id, "title": payload["title"][:80]},
                    )
                    return {"id": draft_id, "status": "draft"}

                # 429 rate limit — retry
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    error = BeehiivApiError(
                        f"Rate limited (429): {response.text}",
                        status_code=429,
                        response_body=response.text,
                    )
                    if attempt < max_retries:
                        delay = int(retry_after) if retry_after else base_delay * (4**attempt)
                        logger.warning(
                            "Rate limited, retry %d/%d after %ds",
                            attempt + 1,
                            max_retries,
                            delay,
                        )
                        time.sleep(delay)
                        last_exception = error
                        continue
                    raise error

                # 5xx server error — retry
                if response.status_code >= 500:
                    error = BeehiivApiError(
                        f"Server error ({response.status_code}): {response.text}",
                        status_code=response.status_code,
                        response_body=response.text,
                    )
                    if attempt < max_retries:
                        delay = base_delay * (4**attempt)
                        logger.warning(
                            "Server error %d, retry %d/%d after %ds",
                            response.status_code,
                            attempt + 1,
                            max_retries,
                            delay,
                        )
                        time.sleep(delay)
                        last_exception = error
                        continue
                    raise error

                # 4xx (non-429) — do NOT retry, raise immediately
                logger.error(
                    "Beehiiv API error %d: %s",
                    response.status_code,
                    response.text,
                )
                raise BeehiivApiError(
                    f"Client error ({response.status_code}): {response.text}",
                    status_code=response.status_code,
                    response_body=response.text,
                )

            except httpx.TimeoutException as e:
                error = BeehiivApiError(f"Request timed out: {e}")
                if attempt < max_retries:
                    delay = base_delay * (4**attempt)
                    logger.warning(
                        "Timeout, retry %d/%d after %ds: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        str(e),
                    )
                    time.sleep(delay)
                    last_exception = error
                    continue
                raise error from e

            except httpx.HTTPError as e:
                error = BeehiivApiError(f"HTTP error: {e}")
                if attempt < max_retries:
                    delay = base_delay * (4**attempt)
                    logger.warning(
                        "HTTP error, retry %d/%d after %ds: %s",
                        attempt + 1,
                        max_retries,
                        delay,
                        str(e),
                    )
                    time.sleep(delay)
                    last_exception = error
                    continue
                raise error from e

        # Should not reach here, but safety net
        if last_exception:
            raise last_exception
        raise BeehiivApiError("Unexpected retry loop exit")
