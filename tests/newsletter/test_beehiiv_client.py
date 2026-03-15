"""Tests for Beehiiv API client module (Story 4.3).

All tests mock HTTP calls — no live Beehiiv API requests are made.
Config attributes are patched via monkeypatch.setattr, following the same
pattern as tests/summarization/test_claude_client.py.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.newsletter.beehiiv_client import (
    BeehiivAPIError,
    BeehiivRetryableError,
    _markdown_to_html,
    push_draft,
)

# ---------------------------------------------------------------------------
# Fixtures dir
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

PUB_ID = "pub_test123"
API_KEY = "key_test_abc"
SUCCESS_BODY = _load_fixture("beehiiv_create_post_201.json")
ERROR_429_BODY = _load_fixture("beehiiv_error_429.json")


def make_mock_response(status_code: int, body: dict) -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.text = json.dumps(body)
    return mock


@pytest.fixture
def mock_beehiiv_config(monkeypatch):
    """Patch config with test Beehiiv credentials."""
    import src.common.config as cfg

    monkeypatch.setattr(cfg, "BEEHIIV_API_KEY", API_KEY)
    monkeypatch.setattr(cfg, "BEEHIIV_PUBLICATION_ID", PUB_ID)


# patch target for requests.post — _post_draft now owns the headers build
_REQUESTS_PATCH = "src.newsletter.beehiiv_client.requests.post"


# ---------------------------------------------------------------------------
# Task 2.1 — correct URL
# ---------------------------------------------------------------------------


def test_push_draft_posts_to_correct_url(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("Title", "## Content")

    called_url = mock_post.call_args[0][0]
    assert called_url == f"https://api.beehiiv.com/v2/publications/{PUB_ID}/posts"


# ---------------------------------------------------------------------------
# Task 2.2 — request body: status=draft, title, body_content
# ---------------------------------------------------------------------------


def test_push_draft_sends_status_draft(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("Title", "## Content")

    payload = mock_post.call_args[1]["json"]
    assert payload["status"] == "draft"


def test_push_draft_payload_contains_title(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("My Newsletter Title", "## Content")

    payload = mock_post.call_args[1]["json"]
    assert payload["title"] == "My Newsletter Title"


def test_push_draft_payload_contains_body_content_as_html(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("Title", "## Section\n\nSome text.")

    payload = mock_post.call_args[1]["json"]
    assert "<h2>" in payload["body_content"]
    assert "Section" in payload["body_content"]


# ---------------------------------------------------------------------------
# Task 2.3 — Authorization header format
# ---------------------------------------------------------------------------


def test_push_draft_authorization_header_format(mock_beehiiv_config):
    with patch(_REQUESTS_PATCH) as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("Title", "## Content")

    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == f"Bearer {API_KEY}"


def test_push_draft_content_type_header(mock_beehiiv_config):
    with patch(_REQUESTS_PATCH) as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        push_draft("Title", "## Content")

    headers = mock_post.call_args[1]["headers"]
    assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Task 2.4 — returns post ID from response
# ---------------------------------------------------------------------------


def test_push_draft_returns_post_id(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)
        result = push_draft("Title", "## Content")

    assert result == "post_abc123"


# ---------------------------------------------------------------------------
# Task 2.5 — 429 triggers retry
# ---------------------------------------------------------------------------


def test_push_draft_429_triggers_retry_and_succeeds(mock_beehiiv_config, monkeypatch):
    monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.side_effect = [
            make_mock_response(429, ERROR_429_BODY),
            make_mock_response(201, SUCCESS_BODY),
        ]
        result = push_draft("Title", "Content")

    assert result == "post_abc123"
    assert mock_post.call_count == 2


def test_push_draft_429_exhausted_raises(mock_beehiiv_config, monkeypatch):
    monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(429, ERROR_429_BODY)

        with pytest.raises(BeehiivRetryableError):
            push_draft("Title", "Content")

    assert mock_post.call_count == 4  # 1 initial + 3 retries


# ---------------------------------------------------------------------------
# Task 2.6 — 500 triggers retry
# ---------------------------------------------------------------------------


def test_push_draft_500_triggers_retry_and_succeeds(mock_beehiiv_config, monkeypatch):
    monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.side_effect = [
            make_mock_response(500, {"error": "internal_server_error"}),
            make_mock_response(201, SUCCESS_BODY),
        ]
        result = push_draft("Title", "Content")

    assert result == "post_abc123"
    assert mock_post.call_count == 2


# ---------------------------------------------------------------------------
# Task 2.7 — non-429 4xx raises immediately, no retry
# ---------------------------------------------------------------------------


def test_push_draft_400_raises_immediately_no_retry(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(400, {"error": "bad_request"})

        with pytest.raises(BeehiivAPIError):
            push_draft("Title", "Content")

    assert mock_post.call_count == 1


def test_push_draft_401_raises_immediately_no_retry(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(401, {"error": "unauthorized"})

        with pytest.raises(BeehiivAPIError):
            push_draft("Title", "Content")

    assert mock_post.call_count == 1


def test_push_draft_403_raises_immediately_no_retry(mock_beehiiv_config):
    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(403, {"error": "forbidden"})

        with pytest.raises(BeehiivAPIError):
            push_draft("Title", "Content")

    assert mock_post.call_count == 1


# ---------------------------------------------------------------------------
# Task 2.8 — key rotation
# ---------------------------------------------------------------------------


def test_push_draft_key_rotation_uses_new_key_on_next_call(monkeypatch):
    """Verify credentials are read from config at call time, not cached at import."""
    import src.common.config as cfg

    monkeypatch.setattr(cfg, "BEEHIIV_PUBLICATION_ID", PUB_ID)

    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(201, SUCCESS_BODY)

        monkeypatch.setattr(cfg, "BEEHIIV_API_KEY", "old_key")
        push_draft("Title", "Content")
        old_auth = mock_post.call_args[1]["headers"]["Authorization"]

        monkeypatch.setattr(cfg, "BEEHIIV_API_KEY", "new_key")
        push_draft("Title", "Content")
        new_auth = mock_post.call_args[1]["headers"]["Authorization"]

    assert old_auth == "Bearer old_key"
    assert new_auth == "Bearer new_key"


def test_push_draft_key_rotation_honoured_within_retry_sequence(monkeypatch):
    """Each retry attempt re-reads BEEHIIV_API_KEY from config (H1 fix verification)."""
    import src.common.config as cfg

    monkeypatch.setattr(cfg, "BEEHIIV_PUBLICATION_ID", PUB_ID)
    monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

    captured_auth_headers = []

    def side_effect(url, **kwargs):
        captured_auth_headers.append(kwargs["headers"]["Authorization"])
        if len(captured_auth_headers) == 1:
            # Rotate key after first attempt
            monkeypatch.setattr(cfg, "BEEHIIV_API_KEY", "rotated_key")
            return make_mock_response(429, ERROR_429_BODY)
        return make_mock_response(201, SUCCESS_BODY)

    monkeypatch.setattr(cfg, "BEEHIIV_API_KEY", "original_key")
    with patch(_REQUESTS_PATCH, side_effect=side_effect):
        result = push_draft("Title", "Content")

    assert result == "post_abc123"
    assert captured_auth_headers[0] == "Bearer original_key"
    assert captured_auth_headers[1] == "Bearer rotated_key"


# ---------------------------------------------------------------------------
# Task 2.9 — _markdown_to_html conversions
# ---------------------------------------------------------------------------


def test_markdown_to_html_converts_h2_heading():
    html = _markdown_to_html("## Section Title")
    assert "<h2>" in html
    assert "Section Title" in html


def test_markdown_to_html_converts_h3_heading():
    html = _markdown_to_html("### Post Title")
    assert "<h3>" in html
    assert "Post Title" in html


def test_markdown_to_html_converts_bold():
    html = _markdown_to_html("**bold text**")
    assert "<strong>bold text</strong>" in html


def test_markdown_to_html_converts_link():
    html = _markdown_to_html("[Read more](https://example.com)")
    assert 'href="https://example.com"' in html
    assert "Read more" in html


def test_markdown_to_html_returns_string():
    result = _markdown_to_html("Plain text content")
    assert isinstance(result, str)
    assert "Plain text content" in result


# ---------------------------------------------------------------------------
# Task 2.10 — error logging on exhausted retries
# ---------------------------------------------------------------------------


def test_error_logging_on_exhausted_retries(mock_beehiiv_config, monkeypatch, caplog):
    import logging

    monkeypatch.setattr("src.common.retry.time.sleep", lambda x: None)

    with patch("src.newsletter.beehiiv_client.requests.post") as mock_post:
        mock_post.return_value = make_mock_response(429, ERROR_429_BODY)

        with caplog.at_level(logging.ERROR, logger="src.newsletter.beehiiv_client"):
            with pytest.raises(BeehiivRetryableError):
                push_draft("Title", "Content")

    # At least one ERROR log should mention the status code
    error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_logs) >= 1
    assert any("429" in r.getMessage() for r in error_logs)
