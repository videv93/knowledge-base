"""Tests for dags/ingestion_daily.py and dags/common.py."""

import importlib.util
import logging
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

# Load dags/common.py by file path to avoid name conflicts with tests/common/
_common_path = Path(__file__).resolve().parents[2] / "dags" / "common.py"
_spec = importlib.util.spec_from_file_location("dags_common", _common_path)
_dags_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dags_common)

DEFAULT_ARGS = _dags_common.DEFAULT_ARGS
on_failure_callback = _dags_common.on_failure_callback


class TestDefaultArgs:
    """Tests for shared DAG defaults."""

    def test_retries_is_three(self):
        assert DEFAULT_ARGS["retries"] == 3

    def test_retry_delay_is_30_seconds(self):
        assert DEFAULT_ARGS["retry_delay"] == timedelta(seconds=30)

    def test_retry_exponential_backoff_enabled(self):
        assert DEFAULT_ARGS["retry_exponential_backoff"] is True

    def test_max_retry_delay_is_480_seconds(self):
        assert DEFAULT_ARGS["max_retry_delay"] == timedelta(seconds=480)

    def test_email_on_failure_enabled(self):
        assert DEFAULT_ARGS["email_on_failure"] is True

    def test_email_on_retry_disabled(self):
        assert DEFAULT_ARGS["email_on_retry"] is False

    def test_on_failure_callback_set(self):
        assert DEFAULT_ARGS["on_failure_callback"] is on_failure_callback

    def test_email_key_exists(self):
        """Email list is configured (may be None if env var not set)."""
        assert "email" in DEFAULT_ARGS


class TestAlertEmails:
    """Tests for ALERT_EMAILS configuration."""

    def test_alert_emails_is_list(self):
        assert isinstance(_dags_common.ALERT_EMAILS, list)

    def test_alert_emails_empty_when_env_not_set(self):
        """No AIRFLOW_ALERT_EMAILS env var → empty list."""
        assert _dags_common.ALERT_EMAILS == []


class TestOnFailureCallback:
    """Tests for on_failure_callback."""

    def test_logs_expected_fields(self, caplog):
        mock_dag = MagicMock()
        mock_dag.dag_id = "test_dag"
        mock_ti = MagicMock()
        mock_ti.task_id = "test_task"

        context = {
            "dag": mock_dag,
            "task_instance": mock_ti,
            "execution_date": "2026-02-24T00:00:00",
            "exception": ValueError("test error"),
        }

        with caplog.at_level(logging.ERROR):
            on_failure_callback(context)

        assert "test_dag" in caplog.text
        assert "test_task" in caplog.text
        assert "2026-02-24" in caplog.text
        assert "test error" in caplog.text

    def test_handles_missing_exception(self, caplog):
        mock_dag = MagicMock()
        mock_dag.dag_id = "test_dag"
        mock_ti = MagicMock()
        mock_ti.task_id = "test_task"

        context = {
            "dag": mock_dag,
            "task_instance": mock_ti,
            "execution_date": "2026-02-24T00:00:00",
        }

        with caplog.at_level(logging.ERROR):
            on_failure_callback(context)

        assert "Unknown" in caplog.text
