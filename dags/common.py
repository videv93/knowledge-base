"""Shared DAG defaults applied to all pipeline DAGs.

All DAGs should import DEFAULT_ARGS and on_failure_callback from this module.

Email alerting requires Airflow SMTP configuration in airflow.cfg or env vars:
  AIRFLOW__SMTP__SMTP_HOST, AIRFLOW__SMTP__SMTP_PORT, etc.
Slack alerting can be added via SlackWebhookOperator in on_failure_callback
when SLACK_WEBHOOK_URL env var is configured.
"""

import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)

# Operator email list for failure alerts (comma-separated in env var)
ALERT_EMAILS = [
    e.strip()
    for e in os.environ.get("AIRFLOW_ALERT_EMAILS", "").split(",")
    if e.strip()
]


def on_failure_callback(context):
    """Log task failure details for alerting and debugging.

    Logs structured error context. Email alerts are handled by Airflow's
    built-in email_on_failure mechanism. Slack integration is available
    when SLACK_WEBHOOK_URL is configured in the Airflow environment.
    """
    logger.error(
        "Task failed: dag_id=%s, task_id=%s, execution_date=%s, exception=%s",
        context["dag"].dag_id,
        context["task_instance"].task_id,
        context["execution_date"],
        context.get("exception", "Unknown"),
    )


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
