"""Tests for DAG helper functions in dags/ingestion_daily.py."""

import importlib.util
import logging
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

_dags_dir = Path(__file__).resolve().parents[2] / "dags"


def _load_ingestion_daily():
    """Lazy-load ingestion_daily module with mocked airflow dependencies.

    Temporarily overrides sys.modules["common"] to point to dags/common.py
    (matching Airflow's runtime behavior where dags/ is on sys.path).
    """
    # Save and override "common" module to point to dags/common.py
    original_common = sys.modules.get("common")
    common_spec = importlib.util.spec_from_file_location("common", _dags_dir / "common.py")
    common_mod = importlib.util.module_from_spec(common_spec)
    sys.modules["common"] = common_mod
    common_spec.loader.exec_module(common_mod)

    # Mock airflow modules
    saved = {}
    for mod_name, attrs in [
        ("airflow", {"DAG": MagicMock()}),
        ("airflow.operators", {}),
        ("airflow.operators.python", {"PythonOperator": MagicMock()}),
    ]:
        saved[mod_name] = sys.modules.get(mod_name)
        mock_mod = types.ModuleType(mod_name)
        for k, v in attrs.items():
            setattr(mock_mod, k, v)
        sys.modules[mod_name] = mock_mod

    try:
        spec = importlib.util.spec_from_file_location("ingestion_daily", _dags_dir / "ingestion_daily.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        # Restore original modules
        if original_common is None:
            sys.modules.pop("common", None)
        else:
            sys.modules["common"] = original_common
        for mod_name, orig in saved.items():
            if orig is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = orig


class TestFetchActiveSources:
    """Tests for _fetch_active_sources helper."""

    def test_returns_serializable_dicts(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
        mock_cursor.fetchall.return_value = [
            (1, "https://blog.example.com/rss", "Test Blog", "DevOps", 8, "active", now, now, now),
        ]

        mod = _load_ingestion_daily()
        result = mod._fetch_active_sources()

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Test Blog"
        assert result[0]["last_checked_at"] == now.isoformat()

    def test_handles_none_datetimes(self, mock_db_connection):
        mock_conn, mock_cursor = mock_db_connection
        mock_cursor.fetchall.return_value = [
            (1, "https://blog.example.com/rss", "Test Blog", "DevOps", 8, "active", None, None, None),
        ]

        mod = _load_ingestion_daily()
        result = mod._fetch_active_sources()

        assert result[0]["last_checked_at"] is None
        assert result[0]["created_at"] is None
        assert result[0]["updated_at"] is None


class TestRunIngestion:
    """Tests for _run_ingestion helper."""

    @patch("src.ingestion.pipeline.run_ingestion")
    def test_reconstructs_sources_and_calls_pipeline(self, mock_pipeline, mock_db_connection):
        from src.common.models import BlogSource

        mock_pipeline.return_value = {
            "total_success": 5,
            "total_duplicates": 2,
            "total_failures": 0,
            "sources_processed": 1,
            "sources_failed": 0,
        }

        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = [
            {
                "id": 1,
                "rss_feed_url": "https://blog.example.com/rss",
                "name": "Test Blog",
                "category": "DevOps",
                "quality_rating": 8,
                "status": "active",
            }
        ]

        mod = _load_ingestion_daily()
        result = mod._run_ingestion(ti=mock_ti)

        mock_pipeline.assert_called_once()
        call_args = mock_pipeline.call_args[0][0]
        assert len(call_args) == 1
        assert isinstance(call_args[0], BlogSource)
        assert call_args[0].name == "Test Blog"
        assert result["total_success"] == 5

    def test_handles_none_xcom(self, mock_db_connection):
        """XCom returns None when upstream task fails or XCom is cleared."""
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        mod = _load_ingestion_daily()
        result = mod._run_ingestion(ti=mock_ti)

        assert result["total_success"] == 0
        assert result["sources_processed"] == 0

    def test_handles_empty_source_list(self, mock_db_connection):
        """No active sources — should return zero metrics without calling pipeline."""
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = []

        mod = _load_ingestion_daily()
        result = mod._run_ingestion(ti=mock_ti)

        assert result["total_success"] == 0
        assert result["sources_processed"] == 0


class TestLogRunSummary:
    """Tests for _log_run_summary helper."""

    def test_logs_metrics(self, caplog):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "total_success": 10,
            "total_duplicates": 3,
            "total_failures": 1,
            "sources_processed": 5,
            "sources_failed": 0,
        }

        mod = _load_ingestion_daily()

        with caplog.at_level(logging.INFO):
            mod._log_run_summary(ti=mock_ti)

        assert "Daily ingestion complete" in caplog.text

    def test_handles_none_metrics(self, caplog):
        """XCom returns None when upstream task failed."""
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        mod = _load_ingestion_daily()

        with caplog.at_level(logging.WARNING):
            mod._log_run_summary(ti=mock_ti)

        assert "No ingestion metrics" in caplog.text
