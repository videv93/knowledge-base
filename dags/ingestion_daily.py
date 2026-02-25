"""Daily RSS ingestion DAG.

Thin orchestrator that fetches active sources, runs the ingestion pipeline,
and logs a run summary. All business logic lives in src/ingestion/ modules.
"""

import json
import logging
from datetime import datetime

from airflow import DAG
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


def _log_run_summary(**kwargs):
    """Pull metrics from XCom and log the run summary."""
    ti = kwargs["ti"]
    metrics = ti.xcom_pull(task_ids="run_ingestion")
    if not metrics:
        logger.warning("No ingestion metrics received from XCom")
        return
    logger.info(
        "Daily ingestion complete: %s",
        json.dumps(metrics, indent=2),
    )


with DAG(
    dag_id="ingestion_daily",
    default_args=DEFAULT_ARGS,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=True,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["ingestion"],
    description="Daily RSS feed ingestion pipeline",
) as dag:

    fetch_active_sources = PythonOperator(
        task_id="fetch_active_sources",
        python_callable=_fetch_active_sources,
    )

    run_ingestion = PythonOperator(
        task_id="run_ingestion",
        python_callable=_run_ingestion,
    )

    log_run_summary = PythonOperator(
        task_id="log_run_summary",
        python_callable=_log_run_summary,
    )

    fetch_active_sources >> run_ingestion >> log_run_summary
