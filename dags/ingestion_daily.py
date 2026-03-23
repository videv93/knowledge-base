"""Daily RSS ingestion DAG.

Thin orchestrator that fetches active sources, runs the ingestion pipeline,
summarizes new posts, runs dbt models, generates vault notes, and logs a run summary.
All business logic lives in src/ modules.
"""

import json
import logging
import os
import shutil
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


def _generate_vault_notes(**kwargs):
    """Generate all vault notes into a temp directory."""
    import tempfile
    from pathlib import Path

    from src.vault.note_generator import generate_all

    tmp_root = Path(tempfile.mkdtemp())
    tmp_dir = tmp_root / "generated"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stats = generate_all(tmp_dir)
    ti = kwargs["ti"]
    ti.xcom_push(key="tmp_generated_dir", value=str(tmp_dir))
    ti.xcom_push(key="tmp_root_dir", value=str(tmp_root))
    return stats


def _validate_notes(**kwargs):
    """Validate generated notes. Logs failures but does not block git push."""
    from pathlib import Path

    from src.vault.note_validator import validate_all

    ti = kwargs["ti"]
    tmp_dir_str = ti.xcom_pull(task_ids="generate_vault_notes", key="tmp_generated_dir")
    if not tmp_dir_str:
        logger.warning("No tmp_generated_dir in XCom — skipping validation")
        return {"passed": 0, "failed": 0}
    tmp_dir = Path(tmp_dir_str)
    summary = validate_all(tmp_dir)
    logger.info("Validation complete: %d passed, %d failed", summary.passed, summary.failed)
    if summary.failed > 0:
        logger.warning("Vault validation: %d notes failed — check logs", summary.failed)
    return {"passed": summary.passed, "failed": summary.failed}


def _publish_vault(**kwargs):
    """Push generated vault to remote repo via GitPublisher."""
    from pathlib import Path

    from src.common import config
    from src.vault.git_publisher import GitPublisher

    ti = kwargs["ti"]
    tmp_dir_str = ti.xcom_pull(task_ids="generate_vault_notes", key="tmp_generated_dir")
    if not tmp_dir_str:
        raise ValueError("tmp_generated_dir XCom not found — generate_vault_notes may have failed")
    tmp_dir = Path(tmp_dir_str)
    stats = ti.xcom_pull(task_ids="generate_vault_notes")

    run_date = kwargs["ds"]
    post_count = stats.get("posts_generated", 0) if stats else 0
    source_count = stats.get("sources_generated", 0) if stats else 0

    publisher = GitPublisher(
        repo_url=config.VAULT_REPO_URL,
        ssh_key_path=config.VAULT_REPO_SSH_KEY_PATH,
        vault_local_path=config.VAULT_LOCAL_PATH,
    )
    publisher.publish(tmp_dir, run_date, post_count, source_count)


def _log_run_summary(**kwargs):
    """Pull metrics from XCom and log the run summary. Cleans up vault temp dir."""
    ti = kwargs["ti"]
    ingestion_metrics = ti.xcom_pull(task_ids="run_ingestion")
    summarization_metrics = ti.xcom_pull(task_ids="summarize_posts")
    vault_gen_stats = ti.xcom_pull(task_ids="generate_vault_notes")
    vault_val_stats = ti.xcom_pull(task_ids="validate_notes")
    summary = {
        "ingestion": ingestion_metrics,
        "summarization": summarization_metrics,
        "vault_generation": vault_gen_stats,
        "vault_validation": vault_val_stats,
    }
    logger.info("Daily pipeline complete: %s", json.dumps(summary, indent=2))

    # Log DLQ health summary for operational visibility
    try:
        from src.common.dlq import get_dlq_summary

        dlq = get_dlq_summary()
        logger.info(
            "DLQ health: %d unresolved entries — %s",
            dlq["total_unresolved"],
            dlq["by_stage"] if dlq["by_stage"] else "none",
        )
    except Exception as exc:
        logger.warning("Failed to retrieve DLQ summary: %s", exc)

    # Cleanup temp dir created by _generate_vault_notes
    tmp_root = ti.xcom_pull(task_ids="generate_vault_notes", key="tmp_root_dir")
    if tmp_root:
        shutil.rmtree(tmp_root, ignore_errors=True)


# Resolve dbt project path relative to the repo root
_DBT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dbt")

with DAG(
    dag_id="ingestion_daily",
    default_args=DEFAULT_ARGS,
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=True,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["ingestion", "summarization", "dbt", "vault"],
    description="Daily RSS feed ingestion, summarization, dbt transformation, and vault generation pipeline",
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

    generate_vault_notes = PythonOperator(
        task_id="generate_vault_notes",
        python_callable=_generate_vault_notes,
    )

    validate_notes = PythonOperator(
        task_id="validate_notes",
        python_callable=_validate_notes,
    )

    git_push_vault = PythonOperator(
        task_id="git_push_vault",
        python_callable=_publish_vault,
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
        >> generate_vault_notes
        >> validate_notes
        >> git_push_vault
        >> log_run_summary
    )
