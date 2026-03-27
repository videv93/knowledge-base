"""AI client for blog post summarization.

Supports two backends:
- OpenRouter (preferred) — uses OpenAI-compatible API via OPENROUTER_API_KEY
- Anthropic direct — uses CLAUDE_API_KEY

OpenRouter is tried first; falls back to Anthropic if OPENROUTER_API_KEY is not set.
"""

import json
import logging

import anthropic
import openai

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
    """Client for AI blog post summarization via OpenRouter or Anthropic."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from src.common import config

        self._backend = self._resolve_backend(api_key, config)
        if self._backend == "openrouter":
            self._openrouter_key = config.OPENROUTER_API_KEY
            self._model = model or config.OPENROUTER_MODEL
            self._openai_client = openai.OpenAI(
                api_key=self._openrouter_key,
                base_url=config.OPENROUTER_BASE_URL,
                timeout=API_TIMEOUT,
            )
            logger.info("Using OpenRouter backend with model %s", self._model)
        else:
            self._api_key = api_key or config.CLAUDE_API_KEY
            self._model = model or config.CLAUDE_MODEL
            if not self._api_key:
                raise RuntimeError(
                    "Either OPENROUTER_API_KEY or CLAUDE_API_KEY is required for summarization. "
                    "Set one in your .env file or environment."
                )
            self._anthropic_client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=API_TIMEOUT,
            )
            logger.info("Using Anthropic backend with model %s", self._model)

    @staticmethod
    def _resolve_backend(api_key: str | None, config) -> str:
        """Determine which backend to use. OpenRouter takes priority."""
        if config.OPENROUTER_API_KEY:
            return "openrouter"
        if api_key or config.CLAUDE_API_KEY:
            return "anthropic"
        return "anthropic"  # will raise in __init__

    @retry_with_backoff(
        max_retries=3,
        base_delay=30,
        exceptions=(
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APITimeoutError,
        ),
    )
    def _call_api(self, prompt: str):
        """Send a prompt and return the raw response (backend-agnostic)."""
        if self._backend == "openrouter":
            return self._call_openrouter(prompt)
        return self._call_anthropic(prompt)

    def _call_anthropic(self, prompt: str) -> anthropic.types.Message:
        return self._anthropic_client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=SUMMARIZATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

    def _call_openrouter(self, prompt: str):
        return self._openai_client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
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
        """
        prompt = SUMMARIZATION_USER_PROMPT_TEMPLATE.replace("{title}", title).replace("{body}", body)

        logger.info("Summarizing post: %s", title[:80])
        response = self._call_api(prompt)

        if self._backend == "openrouter":
            raw_response, response_text = self._extract_openrouter(response)
        else:
            raw_response, response_text = self._extract_anthropic(response)

        return self._parse_response(response_text, raw_response, post_id)

    def _extract_anthropic(self, message) -> tuple[dict, str]:
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
        return raw_response, response_text

    def _extract_openrouter(self, response) -> tuple[dict, str]:
        raw_response = {
            "id": response.id,
            "model": response.model,
            "content": [response.choices[0].message.content],
            "usage": {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }
        response_text = response.choices[0].message.content
        return raw_response, response_text

    def _parse_response(self, text: str, raw_response: dict, post_id: int) -> AiSummary:
        """Parse AI JSON response into an AiSummary."""
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
