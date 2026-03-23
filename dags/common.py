"""Shared DAG defaults applied to all pipeline DAGs.

All DAGs should import DEFAULT_ARGS and DEFAULT_TAGS from this module.

Failure alerting is wired via on_failure_callback → src.common.alerting.send_failure_alert:
  - Email: set ALERT_EMAIL env var (uses local SMTP)
  - Slack: set SLACK_WEBHOOK_URL env var (uses webhook POST)
  - Airflow native email_on_failure: set AIRFLOW_ALERT_EMAILS (comma-separated)
All alerting channels are optional — gracefully skipped if not configured.
"""

import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)

# Read directly from env — DAG config, not business logic. Config boundary applies to src/ only.
ALERT_EMAILS = [e.strip() for e in os.environ.get("AIRFLOW_ALERT_EMAILS", "").split(",") if e.strip()]


def on_failure_callback(context):
    """Log task failure details and dispatch email/Slack alerts.

    Logs structured error context. Additional alerting (email via ALERT_EMAIL,
    Slack via SLACK_WEBHOOK_URL) is dispatched via src.common.alerting.
    Alerting failures are swallowed — they must not block pipeline operations.
    """
    logger.error(
        "Task failed: dag_id=%s, task_id=%s, execution_date=%s, exception=%s",
        context["dag"].dag_id,
        context["task_instance"].task_id,
        context["execution_date"],
        context.get("exception", "Unknown"),
    )
    from src.common.alerting import send_failure_alert

    send_failure_alert(context)


DEFAULT_ARGS = {
    "owner": "knowledge-base",
    "depends_on_past": False,
    "email": ALERT_EMAILS or None,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 3,
    "retry_delay": timedelta(seconds=30),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(seconds=480),
    "on_failure_callback": on_failure_callback,
}

DEFAULT_TAGS = ["knowledge-base"]
