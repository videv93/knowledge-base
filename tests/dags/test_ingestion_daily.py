"""Tests for dags/ingestion_daily.py and dags/common.py."""

import importlib.util
import logging
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            "generate_vault_notes",
            "validate_notes",
            "git_push_vault",
            "log_run_summary",
        }
        assert set(self.operators.keys()) == expected

    def test_task_dependency_chain(self):
        """Verify full >> chain including vault generation tasks."""
        expected_chain = [
            ("fetch_active_sources", "run_ingestion"),
            ("run_ingestion", "summarize_posts"),
            ("summarize_posts", "run_dbt_models"),
            ("run_dbt_models", "test_dbt_models"),
            ("test_dbt_models", "generate_vault_notes"),
            ("generate_vault_notes", "validate_notes"),
            ("validate_notes", "git_push_vault"),
            ("git_push_vault", "log_run_summary"),
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
        assert "vault" in tags

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
    """Tests for the updated _log_run_summary that logs all pipeline metrics."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_logs_all_pipeline_metrics(self, caplog):
        def xcom_pull_side_effect(task_ids, key=None):
            if key == "tmp_root_dir":
                return None
            return {
                "run_ingestion": {"total_success": 5},
                "summarize_posts": {"succeeded": 3, "failed": 1},
                "generate_vault_notes": {"posts_generated": 50, "sources_generated": 10},
                "validate_notes": {"passed": 48, "failed": 2},
            }.get(task_ids)

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        with caplog.at_level(logging.INFO):
            self.mod._log_run_summary(ti=mock_ti)

        assert "Daily pipeline complete" in caplog.text

    def test_includes_vault_stats_in_log(self, caplog):
        def xcom_pull_side_effect(task_ids, key=None):
            if key == "tmp_root_dir":
                return None
            return {
                "run_ingestion": {"total_success": 5},
                "summarize_posts": {"succeeded": 3, "failed": 1},
                "generate_vault_notes": {"posts_generated": 50},
                "validate_notes": {"passed": 48, "failed": 2},
            }.get(task_ids)

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        with caplog.at_level(logging.INFO):
            self.mod._log_run_summary(ti=mock_ti)

        assert "vault_generation" in caplog.text
        assert "vault_validation" in caplog.text

    def test_cleans_up_temp_dir_when_present(self):
        def xcom_pull_side_effect(task_ids, key=None):
            if task_ids == "generate_vault_notes" and key == "tmp_root_dir":
                return "/tmp/fake-vault-root"
            return None

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        with patch("shutil.rmtree") as mock_rmtree:
            self.mod._log_run_summary(ti=mock_ti)

        mock_rmtree.assert_called_once_with("/tmp/fake-vault-root", ignore_errors=True)

    def test_skips_cleanup_when_no_tmp_root(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        with patch("shutil.rmtree") as mock_rmtree:
            self.mod._log_run_summary(ti=mock_ti)

        mock_rmtree.assert_not_called()


class TestGenerateVaultNotesCallable:
    """Tests for the _generate_vault_notes DAG callable."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_calls_generate_all_and_returns_stats(self):
        mock_stats = {
            "posts_generated": 50,
            "sources_generated": 10,
            "authors_generated": 5,
            "total_notes": 65,
        }
        mock_ti = MagicMock()

        vault_mocks = {
            "src": MagicMock(),
            "src.vault": MagicMock(),
            "src.vault.note_generator": MagicMock(),
        }
        with patch.dict(sys.modules, vault_mocks):
            with patch("src.vault.note_generator.generate_all", return_value=mock_stats) as mock_gen:
                with patch("tempfile.mkdtemp", return_value="/tmp/test-vault-123"):
                    result = self.mod._generate_vault_notes(ti=mock_ti, ds="2026-03-13")

        assert result == mock_stats
        # Verify generate_all was called with tmp_root / "generated", not tmp_root itself
        called_path = mock_gen.call_args.args[0]
        assert str(called_path).endswith("/generated"), (
            f"Expected generate_all called with .../generated, got: {called_path}"
        )

    def test_pushes_tmp_generated_dir_to_xcom(self):
        mock_ti = MagicMock()
        mock_stats = {"posts_generated": 10}

        vault_mocks = {
            "src": MagicMock(),
            "src.vault": MagicMock(),
            "src.vault.note_generator": MagicMock(),
        }
        with patch.dict(sys.modules, vault_mocks):
            with patch("src.vault.note_generator.generate_all", return_value=mock_stats):
                with patch("tempfile.mkdtemp", return_value="/tmp/test-vault-456"):
                    self.mod._generate_vault_notes(ti=mock_ti, ds="2026-03-13")

        pushed_keys = {c.kwargs.get("key") for c in mock_ti.xcom_push.call_args_list}
        assert "tmp_generated_dir" in pushed_keys
        assert "tmp_root_dir" in pushed_keys

    def test_src_imports_are_lazy_inside_callable(self):
        """Vault imports must be inside the callable, not at module level."""
        import inspect
        source = inspect.getsource(self.mod._generate_vault_notes)
        # Import should be inside the function body
        assert "from src.vault.note_generator import generate_all" in source


class TestValidateNotesCallable:
    """Tests for the _validate_notes DAG callable."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_calls_validate_all_with_tmp_dir(self):
        mock_summary = MagicMock()
        mock_summary.passed = 48
        mock_summary.failed = 0

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key=None: (
            "/tmp/test-generated" if task_ids == "generate_vault_notes" and key == "tmp_generated_dir" else None
        )

        validator_mocks = {
            "src": MagicMock(),
            "src.vault": MagicMock(),
            "src.vault.note_validator": MagicMock(),
        }
        with patch.dict(sys.modules, validator_mocks):
            with patch("src.vault.note_validator.validate_all", return_value=mock_summary):
                result = self.mod._validate_notes(ti=mock_ti)

        assert result == {"passed": 48, "failed": 0}

    def test_returns_zeros_when_xcom_missing(self, caplog):
        """If tmp_generated_dir XCom is missing, return zeros without raising."""
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        with caplog.at_level(logging.WARNING):
            result = self.mod._validate_notes(ti=mock_ti)

        assert result == {"passed": 0, "failed": 0}
        assert "tmp_generated_dir" in caplog.text

    def test_does_not_raise_on_validation_failures(self):
        """Validation failures must NOT block git push — they only log warnings."""
        mock_summary = MagicMock()
        mock_summary.passed = 40
        mock_summary.failed = 10

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key=None: (
            "/tmp/test-generated" if task_ids == "generate_vault_notes" and key == "tmp_generated_dir" else None
        )

        validator_mocks = {
            "src": MagicMock(),
            "src.vault": MagicMock(),
            "src.vault.note_validator": MagicMock(),
        }
        with patch.dict(sys.modules, validator_mocks):
            with patch("src.vault.note_validator.validate_all", return_value=mock_summary):
                # Should NOT raise even with 10 failures
                result = self.mod._validate_notes(ti=mock_ti)

        assert result["failed"] == 10

    def test_logs_warning_on_failures(self, caplog):
        mock_summary = MagicMock()
        mock_summary.passed = 40
        mock_summary.failed = 5

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key=None: (
            "/tmp/test-generated" if task_ids == "generate_vault_notes" and key == "tmp_generated_dir" else None
        )

        validator_mocks = {
            "src": MagicMock(),
            "src.vault": MagicMock(),
            "src.vault.note_validator": MagicMock(),
        }
        with patch.dict(sys.modules, validator_mocks):
            with patch("src.vault.note_validator.validate_all", return_value=mock_summary):
                with caplog.at_level(logging.WARNING):
                    self.mod._validate_notes(ti=mock_ti)

        assert "5" in caplog.text
        assert "failed" in caplog.text.lower()


class TestPublishVaultCallable:
    """Tests for the _publish_vault DAG callable."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_ingestion_daily()

    def test_calls_publisher_publish_with_correct_args(self):
        gen_stats = {"posts_generated": 55, "sources_generated": 211}

        def xcom_pull_side_effect(task_ids, key=None):
            if task_ids == "generate_vault_notes" and key == "tmp_generated_dir":
                return "/tmp/test-generated"
            if task_ids == "generate_vault_notes":
                return gen_stats
            return None

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        mock_publisher = MagicMock()
        mock_config = MagicMock()
        mock_config.VAULT_REPO_URL = "git@github.com:user/vault.git"
        mock_config.VAULT_REPO_SSH_KEY_PATH = "/home/user/.ssh/id_rsa"
        mock_config.VAULT_LOCAL_PATH = "/tmp/vault-clone"

        import src.common
        with patch.object(src.common, "config", mock_config):
            with patch.dict(sys.modules, {
                "src.vault": MagicMock(),
                "src.vault.git_publisher": MagicMock(),
            }):
                with patch("src.vault.git_publisher.GitPublisher", return_value=mock_publisher):
                    self.mod._publish_vault(ti=mock_ti, ds="2026-03-13")

        mock_publisher.publish.assert_called_once()
        call_args = mock_publisher.publish.call_args
        # publish() uses positional args: (src_generated_dir, run_date, post_count, source_count)
        assert call_args.args[1] == "2026-03-13"

    def test_uses_posts_generated_key_not_post_count(self):
        """Must use stats['posts_generated'], not stats['post_count'] — avoid Story 3.5 bug."""
        gen_stats = {"posts_generated": 42, "sources_generated": 5}

        def xcom_pull_side_effect(task_ids, key=None):
            if task_ids == "generate_vault_notes" and key == "tmp_generated_dir":
                return "/tmp/test-generated"
            if task_ids == "generate_vault_notes":
                return gen_stats
            return None

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        mock_publisher = MagicMock()
        mock_config = MagicMock()
        mock_config.VAULT_REPO_URL = "git@github.com:user/vault.git"
        mock_config.VAULT_REPO_SSH_KEY_PATH = "/home/user/.ssh/id_rsa"
        mock_config.VAULT_LOCAL_PATH = "/tmp/vault-clone"

        import src.common
        with patch.object(src.common, "config", mock_config):
            with patch.dict(sys.modules, {
                "src.vault": MagicMock(),
                "src.vault.git_publisher": MagicMock(),
            }):
                with patch("src.vault.git_publisher.GitPublisher", return_value=mock_publisher):
                    self.mod._publish_vault(ti=mock_ti, ds="2026-03-13")

        call_args = mock_publisher.publish.call_args
        # post_count arg should be 42 (from posts_generated), not 0
        positional_args = call_args.args
        keyword_args = call_args.kwargs
        all_args = list(positional_args) + list(keyword_args.values())
        assert 42 in all_args, f"Expected post_count=42 in publish call args: {call_args}"

    def test_raises_value_error_when_tmp_dir_xcom_missing(self):
        """Missing tmp_generated_dir XCom should raise ValueError with context."""
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None  # all xcom pulls return None

        import pytest as _pytest
        with _pytest.raises(ValueError, match="tmp_generated_dir"):
            self.mod._publish_vault(ti=mock_ti, ds="2026-03-13")

    def test_handles_none_stats_gracefully(self):
        """If gen stats XCom is None, should default to 0 counts."""
        def xcom_pull_side_effect(task_ids, key=None):
            if task_ids == "generate_vault_notes" and key == "tmp_generated_dir":
                return "/tmp/test-generated"
            return None  # stats is None

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        mock_publisher = MagicMock()
        mock_config = MagicMock()
        mock_config.VAULT_REPO_URL = ""
        mock_config.VAULT_REPO_SSH_KEY_PATH = ""
        mock_config.VAULT_LOCAL_PATH = "/tmp/vault-clone"

        import src.common
        with patch.object(src.common, "config", mock_config):
            with patch.dict(sys.modules, {
                "src.vault": MagicMock(),
                "src.vault.git_publisher": MagicMock(),
            }):
                with patch("src.vault.git_publisher.GitPublisher", return_value=mock_publisher):
                    self.mod._publish_vault(ti=mock_ti, ds="2026-03-13")

        # Should not raise — 0 counts used as fallback
        mock_publisher.publish.assert_called_once()
