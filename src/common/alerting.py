"""Pipeline failure alerting.

Provides send_failure_alert() for use as an Airflow on_failure_callback.
Supports email (via smtplib) and Slack (via webhook) alerting.
Both channels are optional — gracefully skipped if not configured.
Alerting failures are caught and logged at WARNING; never re-raised.
"""

import logging
import smtplib
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)


def send_failure_alert(context: dict) -> None:
    """Airflow on_failure_callback — send email and/or Slack alert on task failure.

    Gracefully skips channels with no config. Never raises — alerting must not
    block or fail pipeline operations.

    Args:
        context: Airflow task context dict (contains dag, task_instance, exception, etc.)
    """
    try:
        dag_id = context.get("dag").dag_id
        task_id = context.get("task_instance").task_id
        execution_date = context.get("execution_date")
        exception = context.get("exception")
    except Exception as e:
        logger.warning("send_failure_alert: failed to extract context fields: %s", e)
        return

    message = (
        f"DAG: {dag_id}\n"
        f"Task: {task_id}\n"
        f"Execution: {execution_date}\n"
        f"Error: {exception}"
    )

    _send_email_alert(dag_id, task_id, message)
    _send_slack_alert(dag_id, task_id, message)


def _send_email_alert(dag_id: str, task_id: str, message: str) -> None:
    """Send email alert if ALERT_EMAIL is configured."""
    from src.common import config  # deferred to avoid import-time config validation

    alert_email = getattr(config, "ALERT_EMAIL", None)
    if not alert_email:
        return
    try:
        msg = MIMEText(message)
        msg["Subject"] = f"[Pipeline Alert] {dag_id}.{task_id} failed"
        msg["From"] = alert_email
        msg["To"] = alert_email
        with smtplib.SMTP("localhost") as smtp:
            smtp.send_message(msg)
    except Exception as e:
        logger.warning("Failed to send email alert: %s", e)


def _send_slack_alert(dag_id: str, task_id: str, message: str) -> None:
    """Send Slack alert if SLACK_WEBHOOK_URL is configured."""
    from src.common import config  # deferred to avoid import-time config validation

    slack_url = getattr(config, "SLACK_WEBHOOK_URL", None)
    if not slack_url:
        return
    try:
        payload = {"text": f":red_circle: *{dag_id}.{task_id} FAILED*\n```{message}```"}
        response = requests.post(slack_url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.warning("Failed to send Slack alert: %s", e)
