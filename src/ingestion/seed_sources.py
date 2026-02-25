"""Idempotent seed loader for blog sources.

Reads a CSV file of blog sources and inserts them into raw_blog_sources.
Uses ON CONFLICT DO NOTHING for idempotent loading.
"""

import csv
import logging
from pathlib import Path

from psycopg2.extras import execute_values

from src.common.db import get_connection

logger = logging.getLogger(__name__)

DEFAULT_SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "blog_sources.csv"


def load_sources(csv_path: str | None = None) -> dict:
    """Load blog sources from a CSV file into raw_blog_sources.

    Args:
        csv_path: Path to CSV with columns: name, rss_feed_url, blog_url, category, quality_rating.
                  Defaults to data/blog_sources.csv in the project root.

    Returns:
        Metrics dict: {"inserted": int, "skipped": int, "total": int}
    """
    path = Path(csv_path) if csv_path else DEFAULT_SEED_PATH
    if not path.exists():
        raise FileNotFoundError(f"Seed CSV not found: {path}")

    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append((
                row["rss_feed_url"].strip(),
                row["name"].strip(),
                row["category"].strip(),
                int(row["quality_rating"]),
                "active",
            ))

    total = len(rows)
    logger.info("Parsed %d sources from %s", total, path)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Count existing rows before insert
            cur.execute("SELECT COUNT(*) FROM raw_blog_sources")
            before_count = cur.fetchone()[0]

            execute_values(
                cur,
                "INSERT INTO raw_blog_sources (rss_feed_url, name, category, quality_rating, status) "
                "VALUES %s ON CONFLICT (rss_feed_url) DO NOTHING",
                rows,
            )

            # Count after insert to determine actual inserts
            cur.execute("SELECT COUNT(*) FROM raw_blog_sources")
            after_count = cur.fetchone()[0]

    inserted = after_count - before_count
    skipped = total - inserted

    logger.info(
        "Seed complete: %d inserted, %d skipped (already existed), %d total in CSV",
        inserted, skipped, total,
    )

    return {"inserted": inserted, "skipped": skipped, "total": total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    import sys

    csv_path = sys.argv[1] if len(sys.argv) > 1 else None
    metrics = load_sources(csv_path)
    print(f"Done: {metrics}")
