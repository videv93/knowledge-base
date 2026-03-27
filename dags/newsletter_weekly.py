"""Weekly newsletter generation DAG.

Thin orchestrator that refreshes newsletter candidates via dbt, formats
content, pushes a draft to Beehiiv, and notifies the operator.
All business logic lives in src/newsletter/ modules.
"""

import logging
import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from common import DEFAULT_ARGS, DEFAULT_TAGS

logger = logging.getLogger(__name__)

# Resolve dbt project path relative to the repo root
_DBT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dbt")


def _format_newsletter(**kwargs):
    """Fetch ranked candidates, interleave by category, and format as markdown."""
    from src.common.db import get_connection
    from src.newsletter.content_formatter import (
        fetch_newsletter_candidates,
        format_newsletter_content,
    )

    ti = kwargs["ti"]

    with get_connection() as conn:
        candidates = fetch_newsletter_candidates(conn)

    if not candidates:
        logger.warning("No candidates found for this week's newsletter")
        ti.xcom_push(key="newsletter_content", value="")
        ti.xcom_push(key="candidate_count", value=0)
        return

    content = format_newsletter_content(candidates)

    ti.xcom_push(key="newsletter_content", value=content)
    ti.xcom_push(key="candidate_count", value=len(candidates))
    logger.info(
        "Newsletter formatted: %d candidates, %d chars",
        len(candidates),
        len(content),
    )


def _save_newsletter(**kwargs):
    """Save formatted newsletter as a markdown file for manual Beehiiv upload."""
    from datetime import date
    from pathlib import Path

    ti = kwargs["ti"]
    content = ti.xcom_pull(task_ids="format_newsletter", key="newsletter_content")

    if not content:
        logger.info("No newsletter content — skipping file save")
        ti.xcom_push(key="output_path", value=None)
        return

    today = date.today().isoformat()
    output_dir = Path("/opt/airflow/data/newsletters")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"newsletter_{today}.md"
    output_path.write_text(content, encoding="utf-8")

    ti.xcom_push(key="output_path", value=str(output_path))
    ti.xcom_push(key="draft_title", value=f"Weekly Knowledge Digest - {today}")
    logger.info("Newsletter saved to %s (%d chars)", output_path, len(content))


def _notify_operator(**kwargs):
    """Notify operator that a newsletter file is ready for review."""
    ti = kwargs["ti"]
    output_path = ti.xcom_pull(task_ids="save_newsletter", key="output_path")
    draft_title = ti.xcom_pull(task_ids="save_newsletter", key="draft_title")
    candidate_count = ti.xcom_pull(task_ids="format_newsletter", key="candidate_count") or 0

    if not output_path:
        message = "No newsletter generated this week — no qualifying posts found."
    else:
        message = (
            f"Newsletter ready for review!\n"
            f"Title: {draft_title}\n"
            f"Posts included: {candidate_count}\n"
            f"File: {output_path}\n"
            f"Action: Copy content into Beehiiv UI and publish"
        )

    logger.info(message)

    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if slack_url:
        try:
            import httpx

            httpx.post(slack_url, json={"text": message}, timeout=10)
            logger.info("Slack notification sent")
        except Exception:
            logger.warning("Failed to send Slack notification", exc_info=True)
    else:
        logger.info("No Slack webhook configured — log-only notification")


with DAG(
    dag_id="newsletter_weekly",
    default_args=DEFAULT_ARGS,
    schedule="0 8 * * 1",
    start_date=datetime(2026, 3, 1),
    catchup=False,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["newsletter", "weekly"],
    description="Weekly newsletter generation: dbt refresh, content formatting, Beehiiv draft push",
) as dag:

    refresh_newsletter_candidates = BashOperator(
        task_id="refresh_newsletter_candidates",
        bash_command=(
            f"dbt run --select mart_newsletter_candidates --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR} && "
            f"dbt test --select mart_newsletter_candidates --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR}"
        ),
    )

    format_newsletter = PythonOperator(
        task_id="format_newsletter",
        python_callable=_format_newsletter,
    )

    save_newsletter = PythonOperator(
        task_id="save_newsletter",
        python_callable=_save_newsletter,
    )

    notify_operator = PythonOperator(
        task_id="notify_operator",
        python_callable=_notify_operator,
    )

    (
        refresh_newsletter_candidates
        >> format_newsletter
        >> save_newsletter
        >> notify_operator
    )
