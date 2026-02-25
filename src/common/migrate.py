"""Database migration runner.

Executes SQL migration files from the migrations/ directory in sorted order.
Uses CREATE TABLE IF NOT EXISTS for idempotency.
"""

import logging
from pathlib import Path

from src.common.db import get_connection

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def get_migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> list[Path]:
    """Discover and return migration SQL files sorted by filename.

    Args:
        migrations_dir: Directory containing .sql migration files.

    Returns:
        List of Path objects sorted alphabetically.
    """
    if not migrations_dir.is_dir():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return []

    files = sorted(migrations_dir.glob("*.sql"))
    return files


def run_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Execute all SQL migration files in order.

    Migrations use CREATE TABLE IF NOT EXISTS, making them idempotent.

    Args:
        migrations_dir: Directory containing .sql migration files.

    Returns:
        List of executed migration filenames.
    """
    files = get_migration_files(migrations_dir)

    if not files:
        logger.info("No migration files found in %s", migrations_dir)
        return []

    executed = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            for migration_file in files:
                sql = migration_file.read_text()
                logger.info("Executing migration: %s", migration_file.name)
                try:
                    cur.execute(sql)
                except Exception:
                    logger.error("Migration failed: %s", migration_file.name)
                    raise
                executed.append(migration_file.name)
                logger.info("Completed migration: %s", migration_file.name)

    logger.info("Executed %d migrations", len(executed))
    return executed


if __name__ == "__main__":
    from src.common.logging_config import setup_logging

    setup_logging()
    run_migrations()
