"""Daily RSS ingestion DAG.

Thin orchestrator that fetches active sources, runs the ingestion pipeline,
summarizes new posts, runs dbt models, and logs a run summary.
All business logic lives in src/ modules.
"""

import json
import logging
import os
from datetime import datetime

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from common import DEFAULT_ARGS, DEFAULT_TAGS

logger = logging.getLogger(__name__)


def _fetch_active_sources(**kwargs):
    """Query active sources and push to XCom as JSON-serializable dicts."""
    from src.ingestion.source_loader import get_active_sources

    sources = get_active_sources()
    return [
        {
            "id": s.id,
            "rss_feed_url": s.rss_feed_url,
            "name": s.name,
            "category": s.category,
            "quality_rating": s.quality_rating,
            "status": s.status,
            "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sources
    ]


def _run_ingestion(**kwargs):
    """Pull sources from XCom, reconstruct BlogSource objects, run pipeline."""
    from src.common.models import BlogSource
    from src.ingestion.pipeline import run_ingestion

    ti = kwargs["ti"]
    source_dicts = ti.xcom_pull(task_ids="fetch_active_sources")

    if not source_dicts:
        logger.warning("No active sources received from XCom — skipping ingestion")
        return {
            "total_success": 0,
            "total_duplicates": 0,
            "total_failures": 0,
            "sources_processed": 0,
            "sources_failed": 0,
        }

    sources = [
        BlogSource(
            id=s["id"],
            rss_feed_url=s["rss_feed_url"],
            name=s["name"],
            category=s["category"],
            quality_rating=s["quality_rating"],
            status=s["status"],
        )
        for s in source_dicts
    ]

    metrics = run_ingestion(sources)
    return metrics


def _summarize_posts(**kwargs):
    """Summarize all unsummarized posts. Failures route to DLQ; never raises."""
    from src.summarization.summary_processor import process_all_unsummarized

    result = process_all_unsummarized()
    return {
        "total_found": result.total_found,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
    }


def _log_run_summary(**kwargs):
    """Pull metrics from XCom and log the run summary."""
    ti = kwargs["ti"]
    ingestion_metrics = ti.xcom_pull(task_ids="run_ingestion")
    summarization_metrics = ti.xcom_pull(task_ids="summarize_posts")
    summary = {
        "ingestion": ingestion_metrics,
        "summarization": summarization_metrics,
    }
    logger.info("Daily pipeline complete: %s", json.dumps(summary, indent=2))


# Resolve dbt project path relative to the repo root
_DBT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dbt")

with DAG(
    dag_id="ingestion_daily",
    default_args=DEFAULT_ARGS,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=True,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["ingestion", "summarization", "dbt"],
    description="Daily RSS feed ingestion, summarization, and dbt transformation pipeline",
) as dag:

    fetch_active_sources = PythonOperator(
        task_id="fetch_active_sources",
        python_callable=_fetch_active_sources,
    )

    run_ingestion = PythonOperator(
        task_id="run_ingestion",
        python_callable=_run_ingestion,
    )

    summarize_posts = PythonOperator(
        task_id="summarize_posts",
        python_callable=_summarize_posts,
    )

    run_dbt_models = BashOperator(
        task_id="run_dbt_models",
        bash_command=f"dbt run --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR}",
    )

    test_dbt_models = BashOperator(
        task_id="test_dbt_models",
        bash_command=f"dbt test --project-dir {_DBT_DIR} --profiles-dir {_DBT_DIR}",
    )

    log_run_summary = PythonOperator(
        task_id="log_run_summary",
        python_callable=_log_run_summary,
    )

    (
        fetch_active_sources
        >> run_ingestion
        >> summarize_posts
        >> run_dbt_models
        >> test_dbt_models
        >> log_run_summary
    )
