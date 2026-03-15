"""Tests for dags/newsletter_weekly.py."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_dags_dir = Path(__file__).resolve().parents[2] / "dags"


def _load_newsletter_weekly_dag():
    """Load newsletter_weekly module with mocked airflow dependencies.

    Captures DAG constructor args and operator instantiations for structural testing.
    Returns (module, dag_constructor, operators_created, rshift_calls).
    """
    original_common = sys.modules.get("common")
    common_spec = importlib.util.spec_from_file_location("common", _dags_dir / "common.py")
    common_mod = importlib.util.module_from_spec(common_spec)
    sys.modules["common"] = common_mod
    common_spec.loader.exec_module(common_mod)

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
            "newsletter_weekly_test", _dags_dir / "newsletter_weekly.py"
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


class TestNewsletterWeeklyDagStructure:
    """Tests for the newsletter_weekly DAG structure and task dependencies."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, self.dag_ctor, self.operators, self.rshift_calls = _load_newsletter_weekly_dag()

    def test_dag_id_is_newsletter_weekly(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("dag_id") == "newsletter_weekly"

    def test_schedule_is_weekly(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("schedule") == "@weekly"

    def test_dag_has_expected_task_ids(self):
        expected = {
            "run_dbt_models",
            "test_dbt_models",
            "format_newsletter_content",
            "push_to_beehiiv",
            "notify_draft_ready",
        }
        assert set(self.operators.keys()) == expected

    def test_task_dependency_chain(self):
        """Verify >> chain: run_dbt_models → test_dbt_models → format → push → notify."""
        expected_chain = [
            ("run_dbt_models", "test_dbt_models"),
            ("test_dbt_models", "format_newsletter_content"),
            ("format_newsletter_content", "push_to_beehiiv"),
            ("push_to_beehiiv", "notify_draft_ready"),
        ]
        assert self.rshift_calls == expected_chain

    def test_catchup_is_false(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("catchup") is False

    def test_max_active_runs_is_one(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("max_active_runs") == 1

    def test_uses_default_args_retries(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["retries"] == 3

    def test_uses_default_args_email_on_failure(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["email_on_failure"] is True

    def test_tags_include_newsletter_and_beehiiv(self):
        dag_kwargs = self.dag_ctor.call_args
        tags = dag_kwargs.kwargs.get("tags", [])
        assert "knowledge-base" in tags
        assert "newsletter" in tags
        assert "beehiiv" in tags

    def test_dbt_operators_are_bash_operators(self):
        """run_dbt_models and test_dbt_models should have bash_command."""
        assert self.operators["run_dbt_models"].bash_command is not None
        assert self.operators["test_dbt_models"].bash_command is not None

    def test_dbt_commands_target_correct_model(self):
        run_cmd = self.operators["run_dbt_models"].bash_command
        test_cmd = self.operators["test_dbt_models"].bash_command
        assert "mart_newsletter_candidates" in run_cmd
        assert "mart_newsletter_candidates" in test_cmd
        assert "--project-dir" in run_cmd
        assert "--profiles-dir" in run_cmd

    def test_python_tasks_have_callables(self):
        for task_id in ("format_newsletter_content", "push_to_beehiiv", "notify_draft_ready"):
            assert self.operators[task_id].python_callable is not None


class TestNewsletterWeeklyCallables:
    """Tests for the internal callable functions in newsletter_weekly.py."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, self.operators, _ = _load_newsletter_weekly_dag()

    def test_format_newsletter_content_success(self):
        mock_conn = MagicMock()
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx_mgr.__exit__ = MagicMock(return_value=False)
        mock_generate = MagicMock(return_value="## Newsletter content")

        with patch("src.common.db.get_connection", return_value=mock_ctx_mgr), \
             patch("src.newsletter.content_formatter.generate_newsletter_content", mock_generate):
            result = self.mod._format_newsletter_content()

        assert result == "## Newsletter content"
        mock_generate.assert_called_once_with(mock_conn)

    def test_format_newsletter_content_raises_on_empty(self):
        mock_conn = MagicMock()
        mock_ctx_mgr = MagicMock()
        mock_ctx_mgr.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx_mgr.__exit__ = MagicMock(return_value=False)

        with patch("src.common.db.get_connection", return_value=mock_ctx_mgr), \
             patch("src.newsletter.content_formatter.generate_newsletter_content", return_value=""):
            with pytest.raises(ValueError, match="empty content"):
                self.mod._format_newsletter_content()

    def test_push_to_beehiiv_success(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = "## Newsletter content here"

        with patch("src.newsletter.beehiiv_client.push_draft", return_value="post_abc123"):
            result = self.mod._push_to_beehiiv(ti=mock_ti, ds="2026-03-16")

        assert result == "post_abc123"
        mock_ti.xcom_pull.assert_called_once_with(task_ids="format_newsletter_content")

    def test_push_to_beehiiv_builds_title_with_ds(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = "## Content"

        captured_title = {}

        def fake_push_draft(title, body_content):
            captured_title["title"] = title
            return "post_xyz"

        with patch("src.newsletter.beehiiv_client.push_draft", side_effect=fake_push_draft):
            self.mod._push_to_beehiiv(ti=mock_ti, ds="2026-03-16")

        assert "2026-03-16" in captured_title["title"]

    def test_push_to_beehiiv_raises_if_xcom_empty(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        with pytest.raises(ValueError, match="No newsletter content in XCom"):
            self.mod._push_to_beehiiv(ti=mock_ti, ds="2026-03-16")

    def test_push_to_beehiiv_raises_if_xcom_empty_string(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = ""

        with pytest.raises(ValueError, match="No newsletter content in XCom"):
            self.mod._push_to_beehiiv(ti=mock_ti, ds="2026-03-16")

    def test_notify_draft_ready_logs_post_id(self, caplog):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = "post_abc123"

        import logging
        with caplog.at_level(logging.INFO):
            self.mod._notify_draft_ready(ti=mock_ti, ds="2026-03-16")

        assert "post_abc123" in caplog.text
        mock_ti.xcom_pull.assert_called_once_with(task_ids="push_to_beehiiv")

    def test_notify_draft_ready_raises_if_xcom_empty(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        with pytest.raises(ValueError, match="No Beehiiv post ID in XCom"):
            self.mod._notify_draft_ready(ti=mock_ti, ds="2026-03-16")
