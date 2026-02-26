# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Data pipeline that ingests 211+ blog RSS feeds, generates AI summaries via Claude API, transforms data through dbt, renders Obsidian vault notes, and publishes a weekly newsletter via Beehiiv. Orchestrated by Airflow, backed by Postgres.

## Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/ingestion/test_rss_parser.py -v

# Run a single test
pytest tests/ingestion/test_rss_parser.py::test_name -v

# Lint
ruff check .

# Format
ruff format .

# Start local environment
docker compose up airflow-init && docker compose up -d
```

## Architecture

**Pipeline stages** (each is an epic/module):
1. **Ingestion** (`src/ingestion/`) — RSS parsing → content extraction → Postgres raw tables
2. **Summarization** (`src/summarization/`) — Claude API calls to generate structured summaries (JSON with summary, tags, difficulty)
3. **Vault** (`src/vault/`) — Render Obsidian markdown notes (planned)
4. **Newsletter** (`src/newsletter/`) — Beehiiv publishing (planned)

**Key conventions:**
- `dags/` contains thin Airflow DAG orchestrators with zero business logic — all logic lives in `src/`
- `src/common/config.py` is the single source for all env var access; it validates required vars at import time and fails fast
- `src/common/db.py` provides `get_connection()` context manager — all DB access goes through this
- `src/common/models.py` has shared dataclasses: `BlogSource`, `BlogPost`, `DeadLetterEntry`, `AiSummary`, `ProcessingResult`
- `src/common/dlq.py` handles dead-letter queue for failed posts
- `src/common/retry.py` provides `retry_with_backoff` decorator (used by Claude client for rate limits)
- `migrations/` contains numbered SQL DDL scripts for raw tables

**Test patterns:**
- `tests/conftest.py` has an autouse `mock_env_vars` fixture that sets required Postgres env vars for all tests
- `mock_db_connection` fixture patches `psycopg2.connect` — use it when testing code that hits the DB
- DAG imports are deferred inside task callables to avoid import-time side effects in Airflow

**Config:**
- Python 3.12+, ruff for linting (line-length 120, select E/F/W/I)
- `pyproject.toml` sets `pythonpath = ["."]` so imports use `src.` prefix from project root
