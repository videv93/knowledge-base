"""Structural tests for dbt mart models.

These tests validate dbt model SQL files and schema YAML for correctness
without requiring a live database connection. They act as guardrails to
catch common authoring mistakes (wrong ref() calls, missing schema entries,
missing LIMIT clauses) during CI without needing a running Postgres.
"""

import re
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DBT_ROOT = Path(__file__).parent.parent.parent / "dbt"
MART_MODELS_DIR = DBT_ROOT / "models" / "mart"
MART_SCHEMA_FILE = MART_MODELS_DIR / "schema.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    """Load and parse the mart schema YAML."""
    with MART_SCHEMA_FILE.open() as f:
        return yaml.safe_load(f)


def _get_model_entry(schema: dict, model_name: str) -> dict | None:
    """Return the schema entry for a named model, or None."""
    for model in schema.get("models", []):
        if model["name"] == model_name:
            return model
    return None


def _sql(model_name: str) -> str:
    """Return the SQL source for a mart model."""
    sql_file = MART_MODELS_DIR / f"{model_name}.sql"
    return sql_file.read_text()


# ---------------------------------------------------------------------------
# mart_newsletter_candidates — SQL structure tests
# ---------------------------------------------------------------------------


class TestMartNewsletterCandidatesSql:
    """Validate mart_newsletter_candidates.sql structure and correctness."""

    MODEL = "mart_newsletter_candidates"

    def test_sql_file_exists(self):
        sql_file = MART_MODELS_DIR / f"{self.MODEL}.sql"
        assert sql_file.exists(), f"Missing dbt model file: {sql_file}"

    def test_references_mart_posts_via_ref(self):
        sql = _sql(self.MODEL)
        assert "ref('mart_posts')" in sql, "Model must reference mart_posts via ref()"

    def test_references_mart_sources_via_ref(self):
        sql = _sql(self.MODEL)
        assert "ref('mart_sources')" in sql, "Model must reference mart_sources via ref()"

    def test_does_not_reference_raw_tables(self):
        sql = _sql(self.MODEL)
        raw_tables = ["raw_blog_posts", "raw_blog_sources", "raw_ai_summaries"]
        for raw_table in raw_tables:
            assert raw_table not in sql, (
                f"mart model must not reference raw table '{raw_table}' directly"
            )

    def test_does_not_use_source_macro(self):
        sql = _sql(self.MODEL)
        assert "source(" not in sql, (
            "Mart models must use ref() not source() — source() belongs in staging"
        )

    def test_has_limit_20(self):
        sql = _sql(self.MODEL).lower()
        assert "limit 20" in sql, "Model must select top 20 candidates (limit 20)"

    def test_has_category_rank_window_function(self):
        sql = _sql(self.MODEL).lower()
        assert "row_number()" in sql, "Model must use ROW_NUMBER() for category diversity"
        assert "partition by category" in sql, (
            "ROW_NUMBER() must partition by category for diversity"
        )

    def test_has_7_day_recency_filter(self):
        sql = _sql(self.MODEL).lower()
        assert "7 days" in sql or "7.0 * 86400" in sql or "interval '7 days'" in sql, (
            "Model must filter posts from the last 7 days"
        )

    def test_excludes_null_quality_rating(self):
        sql = _sql(self.MODEL).lower()
        assert "quality_rating is not null" in sql, (
            "Model must exclude sources with null quality_rating to prevent dbt not_null test failures"
        )

    def test_has_diversity_weight_in_rank_score(self):
        sql = _sql(self.MODEL).lower()
        # Diversity component: (6 - category_rank) or (1/category_rank) weighting
        assert "category_rank" in sql and (
            "6 - category_rank" in sql or "1.0 / category_rank" in sql
        ), "rank_score must include a diversity weight based on category_rank (20% component)"

    def test_has_rank_score_column(self):
        sql = _sql(self.MODEL).lower()
        assert "rank_score" in sql, "Model must output a rank_score column"

    def test_has_category_rank_column(self):
        sql = _sql(self.MODEL).lower()
        assert "category_rank" in sql, "Model must output a category_rank column"

    def test_filters_category_rank_lte_5(self):
        sql = _sql(self.MODEL).lower()
        assert "category_rank <= 5" in sql, (
            "Model must cap at 5 candidates per category for diversity"
        )

    def test_excludes_unsummarized_posts(self):
        sql = _sql(self.MODEL).lower()
        assert "summary_text is not null" in sql, (
            "Model must exclude posts without a summary (summary_text is not null)"
        )

    def test_orders_by_rank_score_desc(self):
        sql = _sql(self.MODEL).lower()
        assert "order by rank_score desc" in sql, (
            "Final select must order by rank_score descending"
        )

    def test_selects_post_id_as_alias(self):
        sql = _sql(self.MODEL)
        # Allow both alias styles: "p.id as post_id" or "p.id  as post_id" etc.
        assert re.search(r"\bid\b.*\bpost_id\b", sql, re.IGNORECASE), (
            "Model must alias 'id' as 'post_id' in the SELECT output"
        )

    def test_selects_required_output_columns(self):
        sql = _sql(self.MODEL)
        # Final SELECT must include these output columns
        required = [
            "post_id",
            "title",
            "summary_text",
            "tags",
            "difficulty_classification",
            "author_name",
            "source_name",
            "category",
            "quality_rating",
            "publication_date",
            "url",
            "rank_score",
            "category_rank",
        ]
        for col in required:
            assert col in sql, f"Model must select output column: {col}"


# ---------------------------------------------------------------------------
# mart_newsletter_candidates — Schema YAML tests
# ---------------------------------------------------------------------------


class TestMartNewsletterCandidatesSchema:
    """Validate schema.yml entry for mart_newsletter_candidates."""

    MODEL = "mart_newsletter_candidates"

    def test_schema_file_exists(self):
        assert MART_SCHEMA_FILE.exists(), f"Missing schema file: {MART_SCHEMA_FILE}"

    def test_model_entry_exists(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None, (
            f"'{self.MODEL}' model entry missing from {MART_SCHEMA_FILE.name}"
        )

    def test_model_has_description(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None
        assert entry.get("description"), "Model entry must have a non-empty description"

    def test_required_columns_documented(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None
        documented_cols = {col["name"] for col in entry.get("columns", [])}
        required_cols = {
            "post_id",
            "title",
            "summary_text",
            "author_name",
            "source_name",
            "category",
            "quality_rating",
            "publication_date",
            "url",
            "rank_score",
            "category_rank",
        }
        missing = required_cols - documented_cols
        assert not missing, f"Schema missing column documentation for: {missing}"

    def test_post_id_has_not_null_test(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None
        post_id_col = next(
            (c for c in entry.get("columns", []) if c["name"] == "post_id"), None
        )
        assert post_id_col is not None, "post_id column not in schema"
        tests = post_id_col.get("data_tests", [])
        assert "not_null" in tests, "post_id must have not_null test"

    def test_post_id_has_unique_test(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None
        post_id_col = next(
            (c for c in entry.get("columns", []) if c["name"] == "post_id"), None
        )
        assert post_id_col is not None
        tests = post_id_col.get("data_tests", [])
        assert "unique" in tests, "post_id must have unique test"

    def test_rank_score_has_not_null_test(self):
        schema = _load_schema()
        entry = _get_model_entry(schema, self.MODEL)
        assert entry is not None
        rank_col = next(
            (c for c in entry.get("columns", []) if c["name"] == "rank_score"), None
        )
        assert rank_col is not None, "rank_score column not in schema"
        tests = rank_col.get("data_tests", [])
        assert "not_null" in tests, "rank_score must have not_null test"
