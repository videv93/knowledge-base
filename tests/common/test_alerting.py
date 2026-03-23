"""Tests for src.common.alerting module."""

import smtplib
from unittest.mock import MagicMock, patch

from src.common.alerting import send_failure_alert


def _make_context(
    dag_id="ingestion_daily",
    task_id="fetch_feeds",
    exception=RuntimeError("feed timeout"),
):
    """Create a minimal Airflow-style context dict for testing."""
    mock_dag = MagicMock()
    mock_dag.dag_id = dag_id
    mock_ti = MagicMock()
    mock_ti.task_id = task_id
    return {
        "dag": mock_dag,
        "task_instance": mock_ti,
        "execution_date": "2026-03-22",
        "exception": exception,
    }


def test_send_failure_alert_skips_when_no_config(monkeypatch):
    """No env vars set — function returns without error (graceful no-op)."""
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", None, raising=False)
    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", None, raising=False)
    # Should not raise
    send_failure_alert(_make_context())


def test_send_failure_alert_sends_email_when_configured(monkeypatch):
    """ALERT_EMAIL set — smtplib.SMTP.send_message is called with correct subject/body."""
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", "ops@example.com", raising=False)
    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", None, raising=False)

    with patch("src.common.alerting.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        send_failure_alert(_make_context())

    mock_smtp.send_message.assert_called_once()
    sent_msg = mock_smtp.send_message.call_args[0][0]
    assert "ingestion_daily" in sent_msg["Subject"]
    assert "fetch_feeds" in sent_msg["Subject"]
    assert sent_msg["To"] == "ops@example.com"


def test_send_failure_alert_sends_slack_when_configured(monkeypatch):
    """SLACK_WEBHOOK_URL set — requests.post called with correct payload."""
    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test", raising=False)
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", None, raising=False)

    with patch("src.common.alerting.requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        send_failure_alert(_make_context())

    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert "ingestion_daily" in payload["text"]
    assert "fetch_feeds" in payload["text"]


def test_send_failure_alert_handles_smtp_error_gracefully(monkeypatch):
    """SMTP raises — function logs WARNING and returns without re-raising."""
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", "ops@example.com", raising=False)
    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", None, raising=False)

    with patch("src.common.alerting.smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.side_effect = smtplib.SMTPException("connection refused")
        # Must not raise
        send_failure_alert(_make_context())


def test_send_failure_alert_handles_slack_error_gracefully(monkeypatch):
    """requests.post raises — function logs WARNING and returns without re-raising."""
    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test", raising=False)
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", None, raising=False)

    with patch("src.common.alerting.requests.post") as mock_post:
        mock_post.side_effect = ConnectionError("network unreachable")
        # Must not raise
        send_failure_alert(_make_context())


def test_send_failure_alert_handles_slack_http_error_gracefully(monkeypatch):
    """Slack webhook returns 4xx — raise_for_status raises, function logs WARNING and returns."""
    from requests import HTTPError
    from requests.models import Response

    monkeypatch.setattr("src.common.config.SLACK_WEBHOOK_URL", "https://hooks.slack.com/test", raising=False)
    monkeypatch.setattr("src.common.config.ALERT_EMAIL", None, raising=False)

    mock_response = MagicMock(spec=Response)
    mock_response.raise_for_status.side_effect = HTTPError("400 Bad Request")

    with patch("src.common.alerting.requests.post", return_value=mock_response):
        # Must not raise even when webhook returns an HTTP error
        send_failure_alert(_make_context())


def test_send_failure_alert_handles_none_context_gracefully():
    """Malformed context with None values — function returns without raising."""
    bad_context = {"dag": None, "task_instance": None, "execution_date": None, "exception": None}
    # Must not raise — never blocks pipeline operations
    send_failure_alert(bad_context)
