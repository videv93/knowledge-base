"""Weekly newsletter generation and Beehiiv draft push DAG.

Thin orchestrator: runs dbt to refresh mart_newsletter_candidates,
formats newsletter content, pushes draft to Beehiiv, notifies operator.
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

_DBT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dbt")


def _format_newsletter_content(**kwargs):
    """Fetch candidates, format newsletter, push content to XCom."""
    from src.common.db import get_connection
    from src.newsletter.content_formatter import generate_newsletter_content

    with get_connection() as conn:
        content = generate_newsletter_content(conn)

    if not content:
        raise ValueError("generate_newsletter_content returned empty content")

    logger.info("Newsletter content formatted: %d characters", len(content))
    return content  # Airflow stores return value as XCom


def _push_to_beehiiv(**kwargs):
    """Pull formatted content from XCom, push draft to Beehiiv, return post ID."""
    from src.newsletter.beehiiv_client import push_draft

    ti = kwargs["ti"]
    content = ti.xcom_pull(task_ids="format_newsletter_content")
    if not content:
        raise ValueError("No newsletter content in XCom — format_newsletter_content may have failed")

    run_date = kwargs["ds"]  # Airflow execution date as YYYY-MM-DD string
    title = f"Weekly Knowledge Digest — Week of {run_date}"

    post_id = push_draft(title=title, body_content=content)
    logger.info("Beehiiv draft created: post_id=%s, title=%r", post_id, title)
    return post_id


def _notify_draft_ready(**kwargs):
    """Log draft ready notification with Beehiiv post ID."""
    ti = kwargs["ti"]
    post_id = ti.xcom_pull(task_ids="push_to_beehiiv")
    if not post_id:
        raise ValueError("No Beehiiv post ID in XCom — push_to_beehiiv may have failed")
    run_date = kwargs["ds"]

    logger.info(
        "Newsletter draft ready for review: post_id=%s, week_of=%s — "
        "Review and approve in Beehiiv UI before sending.",
        post_id,
        run_date,
    )


with DAG(
    dag_id="newsletter_weekly",
    default_args=DEFAULT_ARGS,
    schedule="@weekly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["newsletter", "beehiiv"],
    description="Weekly newsletter draft generation and Beehiiv push",
) as dag:
    run_dbt_models = BashOperator(
        task_id="run_dbt_models",
        bash_command=f"dbt run --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR} --select mart_newsletter_candidates",
    )

    test_dbt_models = BashOperator(
        task_id="test_dbt_models",
        bash_command=f"dbt test --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR} --select mart_newsletter_candidates",
    )

    format_newsletter_content = PythonOperator(
        task_id="format_newsletter_content",
        python_callable=_format_newsletter_content,
    )

    push_to_beehiiv = PythonOperator(
        task_id="push_to_beehiiv",
        python_callable=_push_to_beehiiv,
    )

    notify_draft_ready = PythonOperator(
        task_id="notify_draft_ready",
        python_callable=_notify_draft_ready,
    )

    run_dbt_models >> test_dbt_models >> format_newsletter_content >> push_to_beehiiv >> notify_draft_ready
