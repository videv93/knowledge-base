"""Claude API client for blog post summarization.

Single entry point for all AI summarization calls.
"""

import json
import logging

import anthropic

from src.common.models import AiSummary
from src.common.retry import retry_with_backoff
from src.summarization.prompt_templates import (
    SUMMARIZATION_SYSTEM_PROMPT,
    SUMMARIZATION_USER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)

VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}
API_TIMEOUT = 30  # seconds per NFR2
MAX_TOKENS = 500


class SummarizationError(Exception):
    """Raised when summarization fails in a non-retryable way."""


class ClaudeClient:
    """Client for Claude API blog post summarization."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from src.common import config

        self._api_key = api_key or config.CLAUDE_API_KEY
        self._model = model or config.CLAUDE_MODEL
        if not self._api_key:
            raise RuntimeError(
                "CLAUDE_API_KEY is required for summarization. "
                "Set it in your .env file or environment."
            )
        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=API_TIMEOUT,
        )

    @retry_with_backoff(
        max_retries=3,
        base_delay=30,
        exceptions=(anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APITimeoutError),
    )
    def _call_api(self, prompt: str) -> anthropic.types.Message:
        """Send a prompt to Claude and return the raw message response."""
        return self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=SUMMARIZATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

    def summarize_post(self, title: str, body: str, post_id: int = 0) -> AiSummary:
        """Summarize a blog post and return structured AiSummary.

        Args:
            title: Blog post title.
            body: Blog post body content.
            post_id: Database ID of the post (for the returned AiSummary).

        Returns:
            AiSummary with summary_text, tags, and difficulty_classification.

        Raises:
            SummarizationError: If the response cannot be parsed or is invalid.
            anthropic.BadRequestError: If the request is malformed (not retried).
        """
        prompt = SUMMARIZATION_USER_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body)

        logger.info("Summarizing post: %s", title[:80])
        message = self._call_api(prompt)

        raw_response = {
            "id": message.id,
            "model": message.model,
            "content": [block.text for block in message.content if block.type == "text"],
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            },
        }

        response_text = message.content[0].text
        return self._parse_response(response_text, raw_response, post_id)

    def _parse_response(self, text: str, raw_response: dict, post_id: int) -> AiSummary:
        """Parse Claude's JSON response into an AiSummary."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise SummarizationError(f"Invalid JSON response: {e}") from e

        summary = data.get("summary")
        tags = data.get("tags")
        difficulty = data.get("difficulty")

        if not summary or not isinstance(summary, str):
            raise SummarizationError("Missing or invalid 'summary' field in response")
        if not tags or not isinstance(tags, list):
            raise SummarizationError("Missing or invalid 'tags' field in response")
        if difficulty not in VALID_DIFFICULTIES:
            raise SummarizationError(
                f"Invalid 'difficulty' value: {difficulty!r}. "
                f"Expected one of: {VALID_DIFFICULTIES}"
            )

        return AiSummary(
            id=None,
            post_id=post_id,
            summary_text=summary,
            tags=[str(t) for t in tags],
            difficulty_classification=difficulty,
            raw_api_response=raw_response,
        )
