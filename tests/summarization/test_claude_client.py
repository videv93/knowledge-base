"""Tests for AI summarization client (Anthropic + OpenRouter backends)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import anthropic
import openai

from src.common.models import AiSummary
from src.summarization.claude_client import ClaudeClient, SummarizationError

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def _make_mock_message(response_text: str) -> MagicMock:
    """Create a mock anthropic Message response."""
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = response_text

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_msg = MagicMock()
    mock_msg.id = "msg_test123"
    mock_msg.model = "claude-sonnet-4-6"
    mock_msg.content = [mock_block]
    mock_msg.usage = mock_usage
    return mock_msg


def _make_mock_openrouter_response(response_text: str) -> MagicMock:
    """Create a mock OpenAI-compatible chat completion response."""
    mock_message = MagicMock()
    mock_message.content = response_text

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50

    mock_response = MagicMock()
    mock_response.id = "chatcmpl-test123"
    mock_response.model = "anthropic/claude-sonnet-4"
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage
    return mock_response


@pytest.fixture
def mock_anthropic_client(monkeypatch):
    """Provide a mocked Anthropic client."""
    monkeypatch.setenv("CLAUDE_API_KEY", "test-key-123")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "test-key-123")
    monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "")

    mock_client = MagicMock()
    with patch("src.summarization.claude_client.anthropic.Anthropic", return_value=mock_client):
        client = ClaudeClient(api_key="test-key-123")
        yield client, mock_client


@pytest.fixture
def mock_openrouter_client(monkeypatch):
    """Provide a mocked OpenRouter client."""
    monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "or-test-key-123")
    monkeypatch.setattr("src.common.config.OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
    monkeypatch.setattr("src.common.config.OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "")

    mock_client = MagicMock()
    with patch("src.summarization.claude_client.openai.OpenAI", return_value=mock_client):
        client = ClaudeClient()
        yield client, mock_client


class TestClaudeClientInit:
    def test_init_with_anthropic_api_key(self, monkeypatch):
        monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "test-key")
        monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "")
        with patch("src.summarization.claude_client.anthropic.Anthropic"):
            client = ClaudeClient(api_key="test-key")
            assert client._backend == "anthropic"

    def test_init_raises_without_any_api_key(self, monkeypatch):
        monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "")
        monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "")
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY or CLAUDE_API_KEY"):
            ClaudeClient(api_key="")

    def test_init_prefers_openrouter(self, monkeypatch):
        monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "claude-key")
        monkeypatch.setattr("src.common.config.OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
        monkeypatch.setattr("src.common.config.OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        with patch("src.summarization.claude_client.openai.OpenAI"):
            client = ClaudeClient()
            assert client._backend == "openrouter"

    def test_init_with_openrouter(self, monkeypatch):
        monkeypatch.setattr("src.common.config.OPENROUTER_API_KEY", "or-key")
        monkeypatch.setattr("src.common.config.CLAUDE_API_KEY", "")
        monkeypatch.setattr("src.common.config.OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
        monkeypatch.setattr("src.common.config.OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        with patch("src.summarization.claude_client.openai.OpenAI"):
            client = ClaudeClient()
            assert client._backend == "openrouter"


class TestSummarizePostAnthropic:
    def test_successful_summarization(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.return_value = _make_mock_message(json.dumps(fixture))

        result = client.summarize_post("Test Title", "Test body", post_id=42)

        assert isinstance(result, AiSummary)
        assert result.post_id == 42
        assert result.summary_text == fixture["summary"]
        assert result.tags == fixture["tags"]
        assert result.difficulty_classification == "intermediate"
        assert result.raw_api_response is not None
        assert result.id is None

    def test_api_called_with_correct_params(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.return_value = _make_mock_message(json.dumps(fixture))

        client.summarize_post("My Title", "My body content")

        call_kwargs = mock_api.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 500
        assert "My Title" in call_kwargs["messages"][0]["content"]
        assert "My body content" in call_kwargs["messages"][0]["content"]


class TestSummarizePostOpenRouter:
    def test_successful_summarization(self, mock_openrouter_client):
        client, mock_api = mock_openrouter_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.chat.completions.create.return_value = _make_mock_openrouter_response(json.dumps(fixture))

        result = client.summarize_post("Test Title", "Test body", post_id=42)

        assert isinstance(result, AiSummary)
        assert result.post_id == 42
        assert result.summary_text == fixture["summary"]
        assert result.tags == fixture["tags"]
        assert result.difficulty_classification == "intermediate"
        assert result.raw_api_response is not None

    def test_api_called_with_correct_params(self, mock_openrouter_client):
        client, mock_api = mock_openrouter_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.chat.completions.create.return_value = _make_mock_openrouter_response(json.dumps(fixture))

        client.summarize_post("My Title", "My body content")

        call_kwargs = mock_api.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "anthropic/claude-sonnet-4"
        assert call_kwargs["max_tokens"] == 500
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "My Title" in messages[1]["content"]

    def test_raw_response_stored(self, mock_openrouter_client):
        client, mock_api = mock_openrouter_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.chat.completions.create.return_value = _make_mock_openrouter_response(json.dumps(fixture))

        result = client.summarize_post("Title", "Body", post_id=1)

        assert result.raw_api_response["id"] == "chatcmpl-test123"
        assert result.raw_api_response["model"] == "anthropic/claude-sonnet-4"
        assert "usage" in result.raw_api_response


class TestResponseParsing:
    def test_invalid_json_raises_error(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message("not valid json")

        with pytest.raises(SummarizationError, match="Invalid JSON"):
            client.summarize_post("Title", "Body")

    def test_missing_summary_field(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message(
            json.dumps({"tags": ["a"], "difficulty": "beginner"})
        )

        with pytest.raises(SummarizationError, match="summary"):
            client.summarize_post("Title", "Body")

    def test_missing_tags_field(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message(
            json.dumps({"summary": "A summary.", "difficulty": "beginner"})
        )

        with pytest.raises(SummarizationError, match="tags"):
            client.summarize_post("Title", "Body")

    def test_invalid_difficulty_value(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message(
            json.dumps({"summary": "A summary.", "tags": ["a"], "difficulty": "expert"})
        )

        with pytest.raises(SummarizationError, match="difficulty"):
            client.summarize_post("Title", "Body")

    def test_empty_summary_raises_error(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message(
            json.dumps({"summary": "", "tags": ["a"], "difficulty": "beginner"})
        )

        with pytest.raises(SummarizationError, match="summary"):
            client.summarize_post("Title", "Body")

    def test_empty_tags_raises_error(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.return_value = _make_mock_message(
            json.dumps({"summary": "A summary.", "tags": [], "difficulty": "beginner"})
        )

        with pytest.raises(SummarizationError, match="tags"):
            client.summarize_post("Title", "Body")


class TestRetryBehaviorAnthropic:
    def test_retries_on_rate_limit(self, mock_anthropic_client, monkeypatch):
        client, mock_api = mock_anthropic_client
        monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
            ),
            _make_mock_message(json.dumps(fixture)),
        ]

        result = client.summarize_post("Title", "Body")
        assert isinstance(result, AiSummary)
        assert mock_api.messages.create.call_count == 2

    def test_retries_on_internal_server_error(self, mock_anthropic_client, monkeypatch):
        client, mock_api = mock_anthropic_client
        monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.side_effect = [
            anthropic.InternalServerError(
                message="Server error",
                response=MagicMock(status_code=500, headers={}),
                body={"error": {"message": "Server error", "type": "server_error"}},
            ),
            _make_mock_message(json.dumps(fixture)),
        ]

        result = client.summarize_post("Title", "Body")
        assert isinstance(result, AiSummary)
        assert mock_api.messages.create.call_count == 2

    def test_does_not_retry_on_bad_request(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        mock_api.messages.create.side_effect = anthropic.BadRequestError(
            message="Bad request",
            response=MagicMock(status_code=400, headers={}),
            body={"error": {"message": "Bad request", "type": "invalid_request_error"}},
        )

        with pytest.raises(anthropic.BadRequestError):
            client.summarize_post("Title", "Body")
        assert mock_api.messages.create.call_count == 1

    def test_retries_on_timeout(self, mock_anthropic_client, monkeypatch):
        client, mock_api = mock_anthropic_client
        monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.side_effect = [
            anthropic.APITimeoutError(request=MagicMock()),
            _make_mock_message(json.dumps(fixture)),
        ]

        result = client.summarize_post("Title", "Body")
        assert isinstance(result, AiSummary)
        assert mock_api.messages.create.call_count == 2


class TestRetryBehaviorOpenRouter:
    def test_retries_on_rate_limit(self, mock_openrouter_client, monkeypatch):
        client, mock_api = mock_openrouter_client
        monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

        fixture = _load_fixture("sample_success_response.json")
        mock_api.chat.completions.create.side_effect = [
            openai.RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429, headers={}),
                body={"error": {"message": "Rate limited", "type": "rate_limit_error"}},
            ),
            _make_mock_openrouter_response(json.dumps(fixture)),
        ]

        result = client.summarize_post("Title", "Body")
        assert isinstance(result, AiSummary)
        assert mock_api.chat.completions.create.call_count == 2


class TestRawApiResponse:
    def test_raw_response_stored(self, mock_anthropic_client):
        client, mock_api = mock_anthropic_client
        fixture = _load_fixture("sample_success_response.json")
        mock_api.messages.create.return_value = _make_mock_message(json.dumps(fixture))

        result = client.summarize_post("Title", "Body", post_id=1)

        assert result.raw_api_response is not None
        assert result.raw_api_response["id"] == "msg_test123"
        assert result.raw_api_response["model"] == "claude-sonnet-4-6"
        assert "usage" in result.raw_api_response
