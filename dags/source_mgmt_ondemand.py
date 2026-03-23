"""On-demand source management DAG.

Thin orchestrator that adds a new blog source, backfills its recent posts
through the full pipeline (ingestion → summarization → dbt → vault), and
publishes to the vault repo. Triggered manually with source parameters.
All business logic lives in src/ modules.
"""

import json
import logging
import os
import shutil
from datetime import datetime

from airflow import DAG
from airflow.models.param import Param
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from common import DEFAULT_ARGS, DEFAULT_TAGS

logger = logging.getLogger(__name__)


def _add_source(**kwargs):
    """Add new source via source_manager and push result to XCom."""
    from src.ingestion.source_manager import add_source

    params = kwargs["params"]
    result = add_source(
        rss_feed_url=params["rss_feed_url"],
        name=params["name"],
        category=params["category"],
        quality_rating=params["quality_rating"],
    )
    logger.info("Add source result: %s", result)
    if result["action"] == "skipped":
        logger.warning("Source already exists: %s", params["rss_feed_url"])
    return result


def _fetch_new_source(**kwargs):
    """Retrieve newly-added source by ID and push BlogSource dict to XCom."""
    from src.ingestion.source_manager import get_source_by_id

    ti = kwargs["ti"]
    add_result = ti.xcom_pull(task_ids="add_source")
    source_id = add_result.get("source_id")

    if source_id is None:
        logger.warning("No source_id in add_source result — source may be a duplicate")
        return None

    source = get_source_by_id(source_id)
    if source is None:
        raise ValueError(f"Source id={source_id} not found after insertion")

    return {
        "id": source.id,
        "rss_feed_url": source.rss_feed_url,
        "name": source.name,
        "category": source.category,
        "quality_rating": source.quality_rating,
        "status": source.status,
    }


def _backfill_ingestion(**kwargs):
    """Parse feed for new source and ingest only posts from last 30 days."""
    from src.common.models import BlogSource
    from src.ingestion.content_extractor import ingest_posts
    from src.ingestion.rss_parser import filter_entries_by_date, parse_feed

    ti = kwargs["ti"]
    source_dict = ti.xcom_pull(task_ids="fetch_new_source")

    if source_dict is None:
        logger.warning("No source data from fetch_new_source — skipping backfill")
        return {"success_count": 0, "duplicate_count": 0, "failure_count": 0, "total_parsed": 0, "filtered_count": 0}

    source = BlogSource(
        id=source_dict["id"],
        rss_feed_url=source_dict["rss_feed_url"],
        name=source_dict["name"],
        category=source_dict["category"],
        quality_rating=source_dict["quality_rating"],
        status=source_dict["status"],
    )

    entries = parse_feed(source)
    filtered = filter_entries_by_date(entries, max_age_days=30)
    if not filtered:
        logger.info("No posts within 30 days for %s", source.name)
        return {
            "success_count": 0,
            "duplicate_count": 0,
            "failure_count": 0,
            "total_parsed": len(entries),
            "filtered_count": len(entries) - len(filtered),
        }

    metrics = ingest_posts(source, filtered)
    metrics["total_parsed"] = len(entries)
    metrics["filtered_count"] = len(entries) - len(filtered)
    return metrics


def _summarize_backfilled(**kwargs):
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


def _log_summary(**kwargs):
    """Pull metrics from XCom and log the run summary. Cleans up vault temp dir."""
    ti = kwargs["ti"]
    add_result = ti.xcom_pull(task_ids="add_source")
    backfill_metrics = ti.xcom_pull(task_ids="backfill_ingestion")
    summarization_metrics = ti.xcom_pull(task_ids="summarize_backfilled")
    vault_gen_stats = ti.xcom_pull(task_ids="generate_vault_notes")
    vault_val_stats = ti.xcom_pull(task_ids="validate_notes")
    summary = {
        "add_source": add_result,
        "backfill_ingestion": backfill_metrics,
        "summarization": summarization_metrics,
        "vault_generation": vault_gen_stats,
        "vault_validation": vault_val_stats,
    }
    logger.info("Source management pipeline complete: %s", json.dumps(summary, indent=2))

    # Cleanup temp dir created by _generate_vault_notes
    tmp_root = ti.xcom_pull(task_ids="generate_vault_notes", key="tmp_root_dir")
    if tmp_root:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _cleanup(**kwargs):
    """Remove any remaining temp directories."""
    ti = kwargs["ti"]
    tmp_root = ti.xcom_pull(task_ids="generate_vault_notes", key="tmp_root_dir")
    if tmp_root:
        shutil.rmtree(tmp_root, ignore_errors=True)
        logger.info("Cleaned up temp directory: %s", tmp_root)


# Resolve dbt project path relative to the repo root
_DBT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dbt")

with DAG(
    dag_id="source_mgmt_ondemand",
    default_args=DEFAULT_ARGS,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["source-management", "backfill"],
    description="On-demand source addition and backfill through full pipeline",
    params={
        "rss_feed_url": Param(type="string", description="RSS feed URL for the new source"),
        "name": Param(type="string", description="Human-readable source name"),
        "category": Param(type="string", description="Source category (e.g., 'software-engineering')"),
        "quality_rating": Param(type="integer", minimum=1, maximum=10, description="Quality rating 1-10"),
    },
) as dag:

    add_source = PythonOperator(
        task_id="add_source",
        python_callable=_add_source,
    )

    fetch_new_source = PythonOperator(
        task_id="fetch_new_source",
        python_callable=_fetch_new_source,
    )

    backfill_ingestion = PythonOperator(
        task_id="backfill_ingestion",
        python_callable=_backfill_ingestion,
    )

    summarize_backfilled = PythonOperator(
        task_id="summarize_backfilled",
        python_callable=_summarize_backfilled,
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

    publish_vault = PythonOperator(
        task_id="publish_vault",
        python_callable=_publish_vault,
    )

    log_summary = PythonOperator(
        task_id="log_summary",
        python_callable=_log_summary,
    )

    (
        add_source
        >> fetch_new_source
        >> backfill_ingestion
        >> summarize_backfilled
        >> run_dbt_models
        >> test_dbt_models
        >> generate_vault_notes
        >> validate_notes
        >> publish_vault
        >> log_summary
    )
