"""On-demand vault regeneration DAG.

Thin orchestrator that clones/pulls the vault repo, regenerates all notes
from mart tables, validates them, and commits/pushes changes.
All business logic lives in src/ modules.
"""

import logging
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from common import DEFAULT_ARGS, DEFAULT_TAGS

logger = logging.getLogger(__name__)


def _clone_or_pull_vault(**kwargs):
    """Clone or pull the vault repository."""
    from src.common.config import VAULT_LOCAL_PATH, VAULT_REPO_SSH_KEY_PATH, VAULT_REPO_URL

    if not VAULT_REPO_URL:
        raise RuntimeError("VAULT_REPO_URL not configured — cannot run vault regeneration")

    from src.vault.git_publisher import GitPublisher

    publisher = GitPublisher(VAULT_REPO_URL, VAULT_REPO_SSH_KEY_PATH, VAULT_LOCAL_PATH)
    publisher._clone_or_pull()
    return VAULT_LOCAL_PATH


def _generate_all_notes(**kwargs):
    """Clear generated/ dir and regenerate all notes from mart tables."""
    import shutil
    from pathlib import Path

    from src.common.config import VAULT_LOCAL_PATH
    from src.vault.note_generator import generate_all

    generated_dir = Path(VAULT_LOCAL_PATH) / "generated"
    # Full regen: clear existing generated content
    if generated_dir.exists():
        shutil.rmtree(generated_dir)
    generated_dir.mkdir(parents=True, exist_ok=True)

    stats = generate_all(generated_dir)
    logger.info("Full vault regeneration complete: %s", stats)
    return stats


def _validate_notes(**kwargs):
    """Validate all generated notes; warn on failures but don't fail the task."""
    from pathlib import Path

    from src.common.config import VAULT_LOCAL_PATH
    from src.vault.note_validator import validate_all

    generated_dir = Path(VAULT_LOCAL_PATH) / "generated"
    summary = validate_all(generated_dir)

    if summary.failed > 0:
        logger.warning("Vault validation: %d/%d notes failed", summary.failed, summary.total)
    else:
        logger.info("Vault validation passed: %d notes OK", summary.total)

    return {"total": summary.total, "passed": summary.passed, "failed": summary.failed}


def _commit_and_push(**kwargs):
    """Commit and push vault changes if any exist."""
    from datetime import date

    from src.common.config import VAULT_LOCAL_PATH, VAULT_REPO_SSH_KEY_PATH, VAULT_REPO_URL
    from src.vault.git_publisher import GitPublisher

    ti = kwargs["ti"]
    stats = ti.xcom_pull(task_ids="generate_all_notes")

    publisher = GitPublisher(VAULT_REPO_URL, VAULT_REPO_SSH_KEY_PATH, VAULT_LOCAL_PATH)

    if not publisher._has_changes():
        logger.info("No changes detected after regeneration — skipping commit")
        return {"pushed": False}

    run_date = date.today().isoformat()
    post_count = stats.get("posts_generated", 0) if stats else 0
    source_count = stats.get("sources_generated", 0) if stats else 0

    publisher.commit_and_push(run_date, post_count, source_count)
    return {"pushed": True, "run_date": run_date}


with DAG(
    dag_id="vault_regen_ondemand",
    default_args=DEFAULT_ARGS,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=DEFAULT_TAGS + ["vault", "regeneration"],
    description="On-demand full vault regeneration from mart tables",
) as dag:

    clone_or_pull_vault = PythonOperator(
        task_id="clone_or_pull_vault",
        python_callable=_clone_or_pull_vault,
    )

    generate_all_notes = PythonOperator(
        task_id="generate_all_notes",
        python_callable=_generate_all_notes,
    )

    validate_notes = PythonOperator(
        task_id="validate_notes",
        python_callable=_validate_notes,
    )

    commit_and_push = PythonOperator(
        task_id="commit_and_push",
        python_callable=_commit_and_push,
    )

    clone_or_pull_vault >> generate_all_notes >> validate_notes >> commit_and_push
