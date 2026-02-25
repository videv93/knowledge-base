# knowledge-base-pipeline

Data pipeline for the knowledge-base Obsidian vault. Ingests blog posts from 211+ RSS sources, generates AI summaries via Claude, transforms data through dbt, renders Obsidian vault notes, and publishes a weekly newsletter via Beehiiv.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your credentials
docker compose up airflow-init
docker compose up -d
```

Airflow UI: http://localhost:8080 (default: airflow/airflow)

## Project Structure

- `dags/` — Airflow DAG orchestrators (thin, no business logic)
- `src/` — All business logic modules
- `dbt/` — dbt models (staging + mart)
- `templates/` — Jinja markdown templates for vault notes
- `migrations/` — SQL DDL scripts for raw tables
- `tests/` — pytest test suite

## Running Tests

```bash
pytest tests/ -v
```
