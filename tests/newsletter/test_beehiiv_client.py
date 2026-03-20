"""Tests for src.newsletter.beehiiv_client module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.newsletter.beehiiv_client import BASE_URL, BeehiivApiError, BeehiivClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures():
    """Load sample Beehiiv API response fixtures."""
    with open(FIXTURES_DIR / "sample_beehiiv_responses.json") as f:
        return json.load(f)


@pytest.fixture
def client():
    """Create a BeehiivClient instance."""
    return BeehiivClient()


@pytest.fixture
def mock_config():
    """Patch config module with test Beehiiv credentials."""
    with patch("src.common.config.BEEHIIV_API_KEY", "test-api-key-123"), patch(
        "src.common.config.BEEHIIV_PUBLICATION_ID", "pub_test456"
    ):
        yield


class TestBeehiivApiError:
    """Tests for BeehiivApiError exception class."""

    def test_error_with_all_attributes(self):
        error = BeehiivApiError("Test error", status_code=401, response_body='{"error": "Unauthorized"}')
        assert str(error) == "Test error"
        assert error.status_code == 401
        assert error.response_body == '{"error": "Unauthorized"}'

    def test_error_with_defaults(self):
        error = BeehiivApiError("Simple error")
        assert str(error) == "Simple error"
        assert error.status_code is None
        assert error.response_body is None

    def test_error_is_exception(self):
        assert issubclass(BeehiivApiError, Exception)


class TestBeehiivClientInit:
    """Tests for BeehiivClient initialization."""

    def test_base_url_set(self, client):
        assert client.base_url == BASE_URL


class TestGetHeaders:
    """Tests for _get_headers() method — API key rotation support."""

    def test_returns_correct_headers(self, client):
        with patch("src.common.config.BEEHIIV_API_KEY", "my-key"):
            headers = client._get_headers()
            assert headers["Authorization"] == "Bearer my-key"
            assert headers["Content-Type"] == "application/json"

    def test_reads_fresh_key_each_call(self, client):
        """AC #3: API key rotation — verify fresh key read each time."""
        with patch("src.common.config.BEEHIIV_API_KEY", "key-v1"):
            headers1 = client._get_headers()
            assert headers1["Authorization"] == "Bearer key-v1"

        with patch("src.common.config.BEEHIIV_API_KEY", "key-v2-rotated"):
            headers2 = client._get_headers()
            assert headers2["Authorization"] == "Bearer key-v2-rotated"

    def test_raises_when_api_key_missing(self, client):
        with patch("src.common.config.BEEHIIV_API_KEY", ""):
            with pytest.raises(BeehiivApiError, match="BEEHIIV_API_KEY is not configured"):
                client._get_headers()


class TestGetPublicationId:
    """Tests for _get_publication_id() method."""

    def test_returns_publication_id(self, client):
        with patch("src.common.config.BEEHIIV_PUBLICATION_ID", "pub_xyz"):
            assert client._get_publication_id() == "pub_xyz"

    def test_raises_when_publication_id_missing(self, client):
        with patch("src.common.config.BEEHIIV_PUBLICATION_ID", ""):
            with pytest.raises(BeehiivApiError, match="BEEHIIV_PUBLICATION_ID is not configured"):
                client._get_publication_id()


class TestMarkdownToHtml:
    """Tests for _markdown_to_html() conversion."""

    def test_converts_heading(self, client):
        html = client._markdown_to_html("## Hello World")
        assert "<h2>" in html
        assert "Hello World" in html

    def test_converts_link(self, client):
        html = client._markdown_to_html("[Click](https://example.com)")
        assert 'href="https://example.com"' in html

    def test_converts_bold(self, client):
        html = client._markdown_to_html("**bold text**")
        assert "<strong>bold text</strong>" in html

    def test_converts_horizontal_rule(self, client):
        html = client._markdown_to_html("---")
        assert "<hr" in html


class TestCreateDraft:
    """Tests for create_draft() method — AC #1."""

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_success_creates_draft(self, mock_post, client, mock_config, fixtures):
        """AC #1: Creates a draft in Beehiiv (not a published send)."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = mock_response

        result = client.create_draft("Weekly Digest", "## Post Title\n**Summary:** text")

        assert result["id"] == "post_abc123"
        assert result["status"] == "draft"

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_request_url_contains_publication_id(self, mock_post, client, mock_config, fixtures):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = mock_response

        client.create_draft("Test", "content")

        call_args = mock_post.call_args
        assert "pub_test456" in call_args[0][0]

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_request_body_has_correct_fields(self, mock_post, client, mock_config, fixtures):
        """Verify request body contains title, body_content (HTML), status=draft."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = mock_response

        client.create_draft("My Newsletter", "## Hello\n**Bold text**")

        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        assert payload["title"] == "My Newsletter"
        assert payload["status"] == "draft"
        assert "body_content" in payload
        assert "<h2>" in payload["body_content"]
        assert "<strong>" in payload["body_content"]

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_request_has_authorization_header(self, mock_post, client, mock_config, fixtures):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = mock_response

        client.create_draft("Test", "content")

        call_args = mock_post.call_args
        headers = call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-api-key-123"
        assert headers["Content-Type"] == "application/json"

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_status_is_always_draft(self, mock_post, client, mock_config, fixtures):
        """Critical: never publish — only draft."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = mock_response

        client.create_draft("Test", "content")

        payload = mock_post.call_args[1]["json"]
        assert payload["status"] == "draft"


class TestRetryOn429:
    """Tests for 429 rate limit retry behavior — AC #2."""

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_429_triggers_retry(self, mock_post, mock_sleep, client, mock_config, fixtures):
        """AC #2: Retries with exponential backoff on 429."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.text = json.dumps(fixtures["error_429"])
        rate_limit_response.headers = {}

        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = fixtures["success_201"]

        mock_post.side_effect = [rate_limit_response, success_response]

        result = client.create_draft("Test", "content")

        assert result["id"] == "post_abc123"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(30)

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_429_respects_retry_after_header(self, mock_post, mock_sleep, client, mock_config, fixtures):
        """AC #2: Uses Retry-After header when present."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.text = json.dumps(fixtures["error_429"])
        rate_limit_response.headers = {"Retry-After": "45"}

        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = fixtures["success_201"]

        mock_post.side_effect = [rate_limit_response, success_response]

        client.create_draft("Test", "content")
        mock_sleep.assert_called_once_with(45)

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_429_exhausted_retries_raises(self, mock_post, mock_sleep, client, mock_config, fixtures):
        """AC #2: After retries exhausted, failure is logged at ERROR level."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429
        rate_limit_response.text = json.dumps(fixtures["error_429"])
        rate_limit_response.headers = {}

        mock_post.return_value = rate_limit_response

        with pytest.raises(BeehiivApiError) as exc_info:
            client.create_draft("Test", "content")

        assert exc_info.value.status_code == 429
        assert mock_post.call_count == 4


class TestRetryOn5xx:
    """Tests for 5xx server error retry behavior — AC #2."""

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_500_triggers_retry(self, mock_post, mock_sleep, client, mock_config, fixtures):
        server_error = MagicMock()
        server_error.status_code = 500
        server_error.text = json.dumps(fixtures["error_500"])

        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = fixtures["success_201"]

        mock_post.side_effect = [server_error, success_response]

        result = client.create_draft("Test", "content")
        assert result["id"] == "post_abc123"
        assert mock_post.call_count == 2

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_5xx_exhausted_raises_with_context(self, mock_post, mock_sleep, client, mock_config, fixtures):
        """AC #2: Raises BeehiivApiError with full response context."""
        server_error = MagicMock()
        server_error.status_code = 503
        server_error.text = "Service Unavailable"

        mock_post.return_value = server_error

        with pytest.raises(BeehiivApiError) as exc_info:
            client.create_draft("Test", "content")

        assert exc_info.value.status_code == 503
        assert "Service Unavailable" in exc_info.value.response_body
        assert mock_post.call_count == 4

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_exponential_backoff_delays(self, mock_post, mock_sleep, client, mock_config, fixtures):
        """Verify backoff: 30s, 120s, 480s."""
        server_error = MagicMock()
        server_error.status_code = 500
        server_error.text = "error"

        mock_post.return_value = server_error

        with pytest.raises(BeehiivApiError):
            client.create_draft("Test", "content")

        delays = [call[0][0] for call in mock_sleep.call_args_list]
        assert delays == [30, 120, 480]


class TestNoRetryOn4xx:
    """Tests for 4xx (non-429) immediate failure — no retry."""

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_401_raises_immediately(self, mock_post, client, mock_config, fixtures):
        """4xx errors (non-429) do NOT retry."""
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.text = json.dumps(fixtures["error_401"])
        mock_post.return_value = error_response

        with pytest.raises(BeehiivApiError) as exc_info:
            client.create_draft("Test", "content")

        assert exc_info.value.status_code == 401
        assert mock_post.call_count == 1

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_403_raises_immediately(self, mock_post, client, mock_config, fixtures):
        error_response = MagicMock()
        error_response.status_code = 403
        error_response.text = json.dumps(fixtures["error_403"])
        mock_post.return_value = error_response

        with pytest.raises(BeehiivApiError) as exc_info:
            client.create_draft("Test", "content")

        assert exc_info.value.status_code == 403
        assert mock_post.call_count == 1

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_400_raises_immediately(self, mock_post, client, mock_config):
        error_response = MagicMock()
        error_response.status_code = 400
        error_response.text = '{"error": "Bad Request"}'
        mock_post.return_value = error_response

        with pytest.raises(BeehiivApiError) as exc_info:
            client.create_draft("Test", "content")

        assert exc_info.value.status_code == 400
        assert mock_post.call_count == 1


class TestApiKeyRotation:
    """Tests for API key rotation support — AC #3."""

    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_uses_fresh_key_per_call(self, mock_post, client, fixtures):
        """AC #3: Next API call uses new key without downtime."""
        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = fixtures["success_201"]
        mock_post.return_value = success_response

        with patch("src.common.config.BEEHIIV_API_KEY", "old-key"), patch(
            "src.common.config.BEEHIIV_PUBLICATION_ID", "pub_test"
        ):
            client.create_draft("Test 1", "content")

        first_headers = mock_post.call_args_list[0][1]["headers"]
        assert first_headers["Authorization"] == "Bearer old-key"

        with patch("src.common.config.BEEHIIV_API_KEY", "new-rotated-key"), patch(
            "src.common.config.BEEHIIV_PUBLICATION_ID", "pub_test"
        ):
            client.create_draft("Test 2", "content")

        second_headers = mock_post.call_args_list[1][1]["headers"]
        assert second_headers["Authorization"] == "Bearer new-rotated-key"


class TestTimeoutHandling:
    """Tests for HTTP timeout handling."""

    @patch("src.newsletter.beehiiv_client.time.sleep")
    @patch("src.newsletter.beehiiv_client.httpx.post")
    def test_timeout_triggers_retry(self, mock_post, mock_sleep, client, mock_config, fixtures):
        success_response = MagicMock()
        success_response.status_code = 201
        success_response.json.return_value = fixtures["success_201"]

        mock_post.side_effect = [httpx.TimeoutException("Connection timed out"), success_response]

        result = client.create_draft("Test", "content")
        assert result["id"] == "post_abc123"
        assert mock_post.call_count == 2
