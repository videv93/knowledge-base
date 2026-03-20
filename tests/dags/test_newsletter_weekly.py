"""Tests for dags/newsletter_weekly.py."""

import importlib.util
import inspect
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_dags_dir = Path(__file__).resolve().parents[2] / "dags"


def _load_newsletter_weekly():
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
        self.mod, self.dag_ctor, self.operators, self.rshift_calls = _load_newsletter_weekly()

    def test_dag_loads_without_errors(self):
        assert self.mod is not None

    def test_dag_id_is_newsletter_weekly(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("dag_id") == "newsletter_weekly"

    def test_schedule_is_weekly_monday(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("schedule") == "0 8 * * 1"

    def test_catchup_is_false(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("catchup") is False

    def test_dag_has_exactly_four_tasks(self):
        assert len(self.operators) == 4

    def test_dag_has_expected_task_ids(self):
        expected = {
            "refresh_newsletter_candidates",
            "format_newsletter",
            "push_to_beehiiv",
            "notify_operator",
        }
        assert set(self.operators.keys()) == expected

    def test_task_dependency_chain(self):
        """Verify >> chain: refresh -> format -> push -> notify."""
        expected_chain = [
            ("refresh_newsletter_candidates", "format_newsletter"),
            ("format_newsletter", "push_to_beehiiv"),
            ("push_to_beehiiv", "notify_operator"),
        ]
        assert self.rshift_calls == expected_chain

    def test_tags_include_expected(self):
        dag_kwargs = self.dag_ctor.call_args
        tags = dag_kwargs.kwargs.get("tags", [])
        assert "knowledge-base" in tags
        assert "newsletter" in tags
        assert "weekly" in tags

    def test_max_active_runs_is_one(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("max_active_runs") == 1

    def test_uses_default_args(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["retries"] == 3
        assert args["owner"] == "knowledge-base"

    def test_refresh_is_bash_operator(self):
        task = self.operators["refresh_newsletter_candidates"]
        assert task.bash_command is not None
        assert "dbt run" in task.bash_command
        assert "dbt test" in task.bash_command
        assert "mart_newsletter_candidates" in task.bash_command

    def test_dbt_commands_use_project_dir(self):
        task = self.operators["refresh_newsletter_candidates"]
        assert "--project-dir" in task.bash_command
        assert "--profiles-dir" in task.bash_command

    def test_format_newsletter_is_python_operator(self):
        task = self.operators["format_newsletter"]
        assert task.python_callable is not None
        assert task.python_callable.__name__ == "_format_newsletter"

    def test_push_to_beehiiv_is_python_operator(self):
        task = self.operators["push_to_beehiiv"]
        assert task.python_callable is not None
        assert task.python_callable.__name__ == "_push_to_beehiiv"

    def test_notify_operator_is_python_operator(self):
        task = self.operators["notify_operator"]
        assert task.python_callable is not None
        assert task.python_callable.__name__ == "_notify_operator"


class TestNewsletterWeeklyCallables:
    """Tests that each callable uses lazy imports and proper patterns."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, self.operators, _ = _load_newsletter_weekly()

    def test_format_newsletter_lazy_imports(self):
        source = inspect.getsource(self.operators["format_newsletter"].python_callable)
        assert "src.newsletter.content_formatter" in source
        assert "fetch_newsletter_candidates" in source
        assert "group_by_category" in source
        assert "format_newsletter_content" in source

    def test_push_to_beehiiv_lazy_imports(self):
        source = inspect.getsource(self.operators["push_to_beehiiv"].python_callable)
        assert "src.newsletter.beehiiv_client" in source
        assert "BeehiivClient" in source

    def test_notify_operator_uses_os_environ_for_slack(self):
        source = inspect.getsource(self.operators["notify_operator"].python_callable)
        assert "SLACK_WEBHOOK_URL" in source

    def test_format_newsletter_pushes_xcom(self):
        source = inspect.getsource(self.operators["format_newsletter"].python_callable)
        assert "xcom_push" in source
        assert "newsletter_content" in source
        assert "candidate_count" in source

    def test_push_to_beehiiv_pulls_xcom(self):
        source = inspect.getsource(self.operators["push_to_beehiiv"].python_callable)
        assert "xcom_pull" in source
        assert "format_newsletter" in source

    def test_notify_operator_pulls_xcom(self):
        source = inspect.getsource(self.operators["notify_operator"].python_callable)
        assert "xcom_pull" in source
        assert "push_to_beehiiv" in source


class TestFormatNewsletterCallable:
    """Tests for _format_newsletter task callable logic."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_newsletter_weekly()

    def test_with_candidates(self):
        mock_candidates = [MagicMock(), MagicMock()]
        mock_ti = MagicMock()

        with patch(
            "src.newsletter.content_formatter.fetch_newsletter_candidates",
            return_value=mock_candidates,
        ), patch(
            "src.newsletter.content_formatter.group_by_category",
            return_value=mock_candidates,
        ), patch(
            "src.newsletter.content_formatter.format_newsletter_content",
            return_value="## Newsletter Content",
        ):
            self.mod._format_newsletter(ti=mock_ti)

        mock_ti.xcom_push.assert_any_call(key="newsletter_content", value="## Newsletter Content")
        mock_ti.xcom_push.assert_any_call(key="candidate_count", value=2)

    def test_with_empty_candidates(self):
        mock_ti = MagicMock()

        with patch(
            "src.newsletter.content_formatter.fetch_newsletter_candidates",
            return_value=[],
        ):
            self.mod._format_newsletter(ti=mock_ti)

        mock_ti.xcom_push.assert_any_call(key="newsletter_content", value="")
        mock_ti.xcom_push.assert_any_call(key="candidate_count", value=0)


class TestPushToBeehiivCallable:
    """Tests for _push_to_beehiiv task callable logic."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_newsletter_weekly()

    def test_creates_draft_with_content(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("format_newsletter", "newsletter_content"): "## Content here",
        }.get((task_ids, key))

        mock_client = MagicMock()
        mock_client.create_draft.return_value = {"id": "post_abc123", "status": "draft"}

        with patch("src.newsletter.beehiiv_client.BeehiivClient", return_value=mock_client):
            self.mod._push_to_beehiiv(ti=mock_ti)

        mock_client.create_draft.assert_called_once()
        call_kwargs = mock_client.create_draft.call_args.kwargs
        assert "Weekly Knowledge Digest" in call_kwargs["title"]
        assert call_kwargs["content"] == "## Content here"
        mock_ti.xcom_push.assert_any_call(key="draft_id", value="post_abc123")

    def test_skips_when_no_content(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("format_newsletter", "newsletter_content"): "",
        }.get((task_ids, key))

        self.mod._push_to_beehiiv(ti=mock_ti)

        mock_ti.xcom_push.assert_any_call(key="draft_id", value=None)


class TestNotifyOperatorCallable:
    """Tests for _notify_operator task callable logic."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_newsletter_weekly()

    def test_with_draft_ready(self, caplog):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("push_to_beehiiv", "draft_id"): "post_abc123",
            ("push_to_beehiiv", "draft_title"): "Weekly Knowledge Digest - 2026-03-23",
            ("format_newsletter", "candidate_count"): 15,
        }.get((task_ids, key))

        with caplog.at_level(logging.INFO):
            self.mod._notify_operator(ti=mock_ti)

        assert "draft ready for review" in caplog.text
        assert "15" in caplog.text

    def test_with_no_newsletter(self, caplog):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("push_to_beehiiv", "draft_id"): None,
            ("push_to_beehiiv", "draft_title"): None,
            ("format_newsletter", "candidate_count"): 0,
        }.get((task_ids, key))

        with caplog.at_level(logging.INFO):
            self.mod._notify_operator(ti=mock_ti)

        assert "No newsletter generated this week" in caplog.text

    def test_slack_notification_sent(self, monkeypatch, caplog):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("push_to_beehiiv", "draft_id"): "post_abc123",
            ("push_to_beehiiv", "draft_title"): "Weekly Knowledge Digest",
            ("format_newsletter", "candidate_count"): 10,
        }.get((task_ids, key))

        with patch("httpx.post") as mock_post, caplog.at_level(logging.INFO):
            self.mod._notify_operator(ti=mock_ti)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        assert "Slack notification sent" in caplog.text

    def test_no_slack_webhook(self, monkeypatch, caplog):
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("push_to_beehiiv", "draft_id"): "post_abc123",
            ("push_to_beehiiv", "draft_title"): "Weekly Knowledge Digest",
            ("format_newsletter", "candidate_count"): 10,
        }.get((task_ids, key))

        with caplog.at_level(logging.INFO):
            self.mod._notify_operator(ti=mock_ti)

        assert "No Slack webhook configured" in caplog.text

    def test_slack_failure_does_not_raise(self, monkeypatch, caplog):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = lambda task_ids, key: {
            ("push_to_beehiiv", "draft_id"): "post_abc123",
            ("push_to_beehiiv", "draft_title"): "Weekly Knowledge Digest",
            ("format_newsletter", "candidate_count"): 10,
        }.get((task_ids, key))

        with patch("httpx.post", side_effect=Exception("network error")), caplog.at_level(
            logging.WARNING
        ):
            self.mod._notify_operator(ti=mock_ti)

        assert "Failed to send Slack notification" in caplog.text
