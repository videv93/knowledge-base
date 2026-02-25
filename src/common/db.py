"""Shared Postgres connection helper.

All database access MUST go through this module.
"""

import logging
from contextlib import contextmanager

import psycopg2

from src.common import config

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """Return a Postgres connection as a context manager.

    Usage:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    """
    conn = psycopg2.connect(
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
