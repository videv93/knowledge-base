"""Tests for dags/ingestion_daily.py and dags/common.py."""

import importlib.util
import logging
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Load dags/common.py by file path to avoid name conflicts with tests/common/
_dags_dir = Path(__file__).resolve().parents[2] / "dags"
_common_path = _dags_dir / "common.py"
_spec = importlib.util.spec_from_file_location("dags_common", _common_path)
_dags_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dags_common)

DEFAULT_ARGS = _dags_common.DEFAULT_ARGS
on_failure_callback = _dags_common.on_failure_callback


def _load_ingestion_daily():
    """Load ingestion_daily module with mocked airflow dependencies.

    Captures DAG constructor args and operator instantiations for structural testing.
    Returns (module, dag_mock, operators_created).
    """
    original_common = sys.modules.get("common")
    common_spec = importlib.util.spec_from_file_location("common", _dags_dir / "common.py")
    common_mod = importlib.util.module_from_spec(common_spec)
    sys.modules["common"] = common_mod
    common_spec.loader.exec_module(common_mod)

    # Track operators created and their >> dependencies
    operators_created = {}
    rshift_calls = []

    class FakeOperator:
        """Fake operator that records task_id and tracks >> calls."""
        def __init__(self, **kwargs):
            self.task_id = kwargs.get("task_id", "unknown")
            self.python_callable = kwargs.get("python_callable")
            self.bash_command = kwargs.get("bash_command")
            self.kwargs = kwargs
            operators_created[self.task_id] = self

        def __rshift__(self, other):
            rshift_calls.append((self.task_id, other.task_id))
            return other

    class FakePythonOperator(FakeOperator):
        pass

    class FakeBashOperator(FakeOperator):
        pass

    dag_mock = MagicMock()
    dag_mock.__enter__ = MagicMock(return_value=dag_mock)
    dag_mock.__exit__ = MagicMock(return_value=False)

    dag_constructor = MagicMock(return_value=dag_mock)

    saved = {}
    for mod_name, attrs in [
        ("airflow", {"DAG": dag_constructor}),
        ("airflow.operators", {}),
        ("airflow.operators.python", {"PythonOperator": FakePythonOperator}),
        ("airflow.operators.bash", {"BashOperator": FakeBashOperator}),
    ]:
        saved[mod_name] = sys.modules.get(mod_name)
        mock_mod = types.ModuleType(mod_name)
        for k, v in attrs.items():
            setattr(mock_mod, k, v)
        sys.modules[mod_name] = mock_mod

    try:
        spec = importlib.util.spec_from_file_location(
            "ingestion_daily_test", _dags_dir / "ingestion_daily.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, dag_constructor, operators_created, rshift_calls
    finally:
        if original_common is None:
            sys.modules.pop("common", None)
        else:
            sys.modules["common"] = original_common
        for mod_name, orig in saved.items():
            if orig is None:
                sys.modules.pop(mod_name, None)
            else:
                sys.modules[mod_name] = orig


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


class TestDagStructure:
    """Tests for the ingestion_daily DAG structure and task dependencies."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, self.dag_ctor, self.operators, self.rshift_calls = _load_ingestion_daily()

    def test_dag_loads_without_errors(self):
        """DAG module loads without import errors."""
        assert self.mod is not None

    def test_dag_id_is_ingestion_daily(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("dag_id") == "ingestion_daily"

    def test_dag_has_expected_task_ids(self):
        expected = {
            "fetch_active_sources",
            "run_ingestion",
            "summarize_posts",
            "run_dbt_models",
            "test_dbt_models",
            "log_run_summary",
        }
        assert set(self.operators.keys()) == expected

    def test_task_dependency_chain(self):
        """Verify >> chain: fetch → ingest → summarize → dbt run → dbt test → log."""
        expected_chain = [
            ("fetch_active_sources", "run_ingestion"),
            ("run_ingestion", "summarize_posts"),
            ("summarize_posts", "run_dbt_models"),
            ("run_dbt_models", "test_dbt_models"),
            ("test_dbt_models", "log_run_summary"),
        ]
        assert self.rshift_calls == expected_chain

    def test_dag_uses_default_args(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["retries"] == 3
        assert args["owner"] == "knowledge-base"

    def test_dag_tags_include_expected(self):
        dag_kwargs = self.dag_ctor.call_args
        tags = dag_kwargs.kwargs.get("tags", [])
        assert "knowledge-base" in tags
        assert "ingestion" in tags
        assert "summarization" in tags
        assert "dbt" in tags

    def test_summarize_posts_is_python_operator(self):
        task = self.operators["summarize_posts"]
        assert task.python_callable is not None
        assert task.python_callable.__name__ == "_summarize_posts"

    def test_run_dbt_models_is_bash_operator(self):
        task = self.operators["run_dbt_models"]
        assert task.bash_command is not None
        assert "dbt run" in task.bash_command

    def test_test_dbt_models_is_bash_operator(self):
        task = self.operators["test_dbt_models"]
        assert task.bash_command is not None
        assert "dbt test" in task.bash_command

    def test_dbt_commands_point_to_dbt_directory(self):
        run_task = self.operators["run_dbt_models"]
        test_task = self.operators["test_dbt_models"]
        assert "--project-dir" in run_task.bash_command
        assert "--profiles-dir" in run_task.bash_command
        assert "--project-dir" in test_task.bash_command
        assert "--profiles-dir" in test_task.bash_command
        # Both should point to same dbt directory
        assert "dbt" in run_task.bash_command
        assert "dbt" in test_task.bash_command

    def test_summarize_posts_calls_module_not_inline_logic(self):
        """The summarize callable must delegate to src/summarization module."""
        import inspect
        task = self.operators["summarize_posts"]
        source = inspect.getsource(task.python_callable)
        assert "process_all_unsummarized" in source

    def test_max_active_runs_is_one(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("max_active_runs") == 1


class TestSummarizePostsCallable:
    """Tests for the _summarize_posts DAG callable function."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_returns_dict_with_expected_keys(self):
        mock_result = MagicMock()
        mock_result.total_found = 10
        mock_result.succeeded = 8
        mock_result.failed = 1
        mock_result.skipped = 1

        with patch(
            "src.summarization.summary_processor.process_all_unsummarized",
            return_value=mock_result,
        ):
            result = self.mod._summarize_posts()

        assert result == {
            "total_found": 10,
            "succeeded": 8,
            "failed": 1,
            "skipped": 1,
        }

    def test_returns_zeros_when_no_posts(self):
        mock_result = MagicMock()
        mock_result.total_found = 0
        mock_result.succeeded = 0
        mock_result.failed = 0
        mock_result.skipped = 0

        with patch(
            "src.summarization.summary_processor.process_all_unsummarized",
            return_value=mock_result,
        ):
            result = self.mod._summarize_posts()

        assert result["total_found"] == 0


class TestLogRunSummaryUpdated:
    """Tests for the updated _log_run_summary that logs both ingestion and summarization."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_logs_both_ingestion_and_summarization_metrics(self, caplog):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids: {
            "run_ingestion": {"total_success": 5},
            "summarize_posts": {"succeeded": 3, "failed": 1},
        }.get(task_ids)

        with caplog.at_level(logging.INFO):
            self.mod._log_run_summary(ti=mock_ti)

        assert "Daily pipeline complete" in caplog.text
