"""Tests for dags/source_mgmt_ondemand.py."""

import importlib.util
import inspect
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load dags/common.py by file path to avoid name conflicts with tests/common/
_dags_dir = Path(__file__).resolve().parents[2] / "dags"


def _load_source_mgmt_dag():
    """Load source_mgmt_ondemand module with mocked airflow dependencies.

    Returns (module, dag_mock, operators_created, rshift_calls).
    """
    original_common = sys.modules.get("common")
    common_spec = importlib.util.spec_from_file_location("common", _dags_dir / "common.py")
    common_mod = importlib.util.module_from_spec(common_spec)
    sys.modules["common"] = common_mod
    common_spec.loader.exec_module(common_mod)

    operators_created = {}
    rshift_calls = []

    class FakeOperator:
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

    class FakeParam:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    dag_mock = MagicMock()
    dag_mock.__enter__ = MagicMock(return_value=dag_mock)
    dag_mock.__exit__ = MagicMock(return_value=False)
    dag_constructor = MagicMock(return_value=dag_mock)

    saved = {}
    for mod_name, attrs in [
        ("airflow", {"DAG": dag_constructor}),
        ("airflow.models", {}),
        ("airflow.models.param", {"Param": FakeParam}),
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
            "source_mgmt_ondemand_test", _dags_dir / "source_mgmt_ondemand.py"
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


class TestDagStructure:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, self.dag_ctor, self.operators, self.rshift_calls = _load_source_mgmt_dag()

    def test_dag_exists_with_correct_id(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("dag_id") == "source_mgmt_ondemand"

    def test_schedule_is_none(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("schedule") is None

    def test_task_chain_order(self):
        expected_chain = [
            ("add_source", "fetch_new_source"),
            ("fetch_new_source", "backfill_ingestion"),
            ("backfill_ingestion", "summarize_backfilled"),
            ("summarize_backfilled", "run_dbt_models"),
            ("run_dbt_models", "test_dbt_models"),
            ("test_dbt_models", "generate_vault_notes"),
            ("generate_vault_notes", "validate_notes"),
            ("validate_notes", "publish_vault"),
            ("publish_vault", "log_summary"),
        ]
        assert self.rshift_calls == expected_chain

    def test_has_expected_task_ids(self):
        expected = {
            "add_source",
            "fetch_new_source",
            "backfill_ingestion",
            "summarize_backfilled",
            "run_dbt_models",
            "test_dbt_models",
            "generate_vault_notes",
            "validate_notes",
            "publish_vault",
            "log_summary",
        }
        assert set(self.operators.keys()) == expected

    def test_params_defined(self):
        dag_kwargs = self.dag_ctor.call_args
        params = dag_kwargs.kwargs.get("params", {})
        assert "rss_feed_url" in params
        assert "name" in params
        assert "category" in params
        assert "quality_rating" in params

    def test_dag_uses_default_args(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["retries"] == 3
        assert args["owner"] == "knowledge-base"

    def test_dbt_commands_point_to_dbt_directory(self):
        run_task = self.operators["run_dbt_models"]
        test_task = self.operators["test_dbt_models"]
        assert "dbt run" in run_task.bash_command
        assert "dbt test" in test_task.bash_command
        assert "--project-dir" in run_task.bash_command
        assert "--profiles-dir" in run_task.bash_command

    def test_max_active_runs_is_one(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("max_active_runs") == 1


class TestAddSource:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_calls_add_source_with_params(self):
        mock_params = {
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test Blog",
            "category": "software-engineering",
            "quality_rating": 8,
        }
        with patch(
            "src.ingestion.source_manager.add_source", return_value={"action": "inserted", "source_id": 42}
        ) as mock_add:
            result = self.mod._add_source(params=mock_params)

        mock_add.assert_called_once_with(
            rss_feed_url="https://example.com/feed.xml",
            name="Test Blog",
            category="software-engineering",
            quality_rating=8,
        )
        assert result == {"action": "inserted", "source_id": 42}

    def test_handles_duplicate_source(self):
        mock_params = {
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test Blog",
            "category": "software-engineering",
            "quality_rating": 8,
        }
        with patch(
            "src.ingestion.source_manager.add_source", return_value={"action": "skipped", "reason": "duplicate"}
        ):
            result = self.mod._add_source(params=mock_params)

        assert result["action"] == "skipped"

    def test_pushes_result_to_xcom(self):
        """Return value auto-pushes to XCom via PythonOperator."""
        mock_params = {
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test Blog",
            "category": "software-engineering",
            "quality_rating": 8,
        }
        with patch("src.ingestion.source_manager.add_source", return_value={"action": "inserted", "source_id": 1}):
            result = self.mod._add_source(params=mock_params)

        assert isinstance(result, dict)
        assert "action" in result


class TestFetchNewSource:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_fetches_source_by_id(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {"action": "inserted", "source_id": 42}

        mock_source = MagicMock()
        mock_source.id = 42
        mock_source.rss_feed_url = "https://example.com/feed.xml"
        mock_source.name = "Test Blog"
        mock_source.category = "software-engineering"
        mock_source.quality_rating = 8
        mock_source.status = "active"

        with patch("src.ingestion.source_manager.get_source_by_id", return_value=mock_source):
            result = self.mod._fetch_new_source(ti=mock_ti)

        assert result["id"] == 42
        assert result["name"] == "Test Blog"
        assert result["status"] == "active"

    def test_returns_none_when_no_source_id(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {"action": "skipped", "reason": "duplicate"}

        result = self.mod._fetch_new_source(ti=mock_ti)
        assert result is None

    def test_returns_serializable_dict(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {"action": "inserted", "source_id": 1}

        mock_source = MagicMock()
        mock_source.id = 1
        mock_source.rss_feed_url = "https://example.com/feed.xml"
        mock_source.name = "Test"
        mock_source.category = "tech"
        mock_source.quality_rating = 5
        mock_source.status = "active"

        with patch("src.ingestion.source_manager.get_source_by_id", return_value=mock_source):
            result = self.mod._fetch_new_source(ti=mock_ti)

        # Verify JSON serializable
        import json

        json.dumps(result)
        assert set(result.keys()) == {"id", "rss_feed_url", "name", "category", "quality_rating", "status"}


class TestBackfillIngestion:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_calls_parse_feed_and_ingest_posts(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "id": 1,
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test",
            "category": "tech",
            "quality_rating": 5,
            "status": "active",
        }

        mock_entries = [
            {
                "title": "Post",
                "url": "https://example.com/1",
                "publication_date": None,
                "body": "",
                "author_name": "Author",
            }
        ]

        with patch("src.ingestion.rss_parser.parse_feed", return_value=mock_entries) as mock_parse:
            with patch("src.ingestion.rss_parser.filter_entries_by_date", return_value=mock_entries) as mock_filter:
                with patch(
                    "src.ingestion.content_extractor.ingest_posts",
                    return_value={"success_count": 1, "duplicate_count": 0, "failure_count": 0},
                ):
                    result = self.mod._backfill_ingestion(ti=mock_ti)

        mock_parse.assert_called_once()
        mock_filter.assert_called_once_with(mock_entries, max_age_days=30)
        assert result["success_count"] == 1

    def test_applies_30_day_filter(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "id": 1,
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test",
            "category": "tech",
            "quality_rating": 5,
            "status": "active",
        }

        all_entries = [{"title": "New"}, {"title": "Old"}]
        filtered_entries = [{"title": "New"}]

        with patch("src.ingestion.rss_parser.parse_feed", return_value=all_entries):
            with patch("src.ingestion.rss_parser.filter_entries_by_date", return_value=filtered_entries):
                with patch(
                    "src.ingestion.content_extractor.ingest_posts",
                    return_value={"success_count": 1, "duplicate_count": 0, "failure_count": 0},
                ):
                    result = self.mod._backfill_ingestion(ti=mock_ti)

        assert result["total_parsed"] == 2
        assert result["filtered_count"] == 1

    def test_returns_metrics_with_filter_counts(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "id": 1,
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test",
            "category": "tech",
            "quality_rating": 5,
            "status": "active",
        }

        with patch(
            "src.ingestion.rss_parser.parse_feed", return_value=[{"title": "A"}, {"title": "B"}, {"title": "C"}]
        ):
            with patch("src.ingestion.rss_parser.filter_entries_by_date", return_value=[{"title": "A"}]):
                with patch(
                    "src.ingestion.content_extractor.ingest_posts",
                    return_value={"success_count": 1, "duplicate_count": 0, "failure_count": 0},
                ):
                    result = self.mod._backfill_ingestion(ti=mock_ti)

        assert "total_parsed" in result
        assert "filtered_count" in result
        assert result["total_parsed"] == 3
        assert result["filtered_count"] == 2

    def test_handles_empty_feed(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "id": 1,
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test",
            "category": "tech",
            "quality_rating": 5,
            "status": "active",
        }

        with patch("src.ingestion.rss_parser.parse_feed", return_value=[]):
            with patch("src.ingestion.rss_parser.filter_entries_by_date", return_value=[]):
                result = self.mod._backfill_ingestion(ti=mock_ti)

        assert result["success_count"] == 0
        assert result["total_parsed"] == 0

    def test_handles_none_source_dict(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = None

        result = self.mod._backfill_ingestion(ti=mock_ti)
        assert result["success_count"] == 0

    def test_skips_posts_older_than_30_days(self):
        mock_ti = MagicMock()
        mock_ti.xcom_pull.return_value = {
            "id": 1,
            "rss_feed_url": "https://example.com/feed.xml",
            "name": "Test",
            "category": "tech",
            "quality_rating": 5,
            "status": "active",
        }

        all_entries = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
        # filter returns only 1 entry (2 were older than 30 days)
        filtered_entries = [{"title": "A"}]

        with patch("src.ingestion.rss_parser.parse_feed", return_value=all_entries):
            with patch("src.ingestion.rss_parser.filter_entries_by_date", return_value=filtered_entries):
                with patch(
                    "src.ingestion.content_extractor.ingest_posts",
                    return_value={"success_count": 1, "duplicate_count": 0, "failure_count": 0},
                ):
                    result = self.mod._backfill_ingestion(ti=mock_ti)

        assert result["filtered_count"] == 2


class TestLogSummary:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_aggregates_all_xcom_metrics(self, caplog):
        def xcom_pull_side_effect(task_ids, key=None):
            if key == "tmp_root_dir":
                return None
            return {
                "add_source": {"action": "inserted", "source_id": 1},
                "backfill_ingestion": {"success_count": 5, "total_parsed": 10},
                "summarize_backfilled": {"succeeded": 5, "failed": 0},
                "generate_vault_notes": {"posts_generated": 50},
                "validate_notes": {"passed": 48, "failed": 2},
            }.get(task_ids)

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        with caplog.at_level(logging.INFO):
            self.mod._log_summary(ti=mock_ti)

        assert "Source management pipeline complete" in caplog.text

    def test_cleans_up_temp_dir(self):
        def xcom_pull_side_effect(task_ids, key=None):
            if task_ids == "generate_vault_notes" and key == "tmp_root_dir":
                return "/tmp/fake-vault-root"
            return None

        mock_ti = MagicMock()
        mock_ti.xcom_pull.side_effect = xcom_pull_side_effect

        with patch("shutil.rmtree") as mock_rmtree:
            self.mod._log_summary(ti=mock_ti)

        mock_rmtree.assert_called_once_with("/tmp/fake-vault-root", ignore_errors=True)


class TestSummarizeBackfilled:
    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_returns_dict_with_expected_keys(self):
        mock_result = MagicMock()
        mock_result.total_found = 10
        mock_result.succeeded = 8
        mock_result.failed = 1
        mock_result.skipped = 1

        with patch("src.summarization.summary_processor.process_all_unsummarized", return_value=mock_result):
            result = self.mod._summarize_backfilled()

        assert result == {"total_found": 10, "succeeded": 8, "failed": 1, "skipped": 1}


class TestLazyImports:
    """Verify all task callables use deferred imports."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, _, _ = _load_source_mgmt_dag()

    def test_add_source_imports_are_lazy(self):
        source = inspect.getsource(self.mod._add_source)
        assert "from src.ingestion.source_manager import add_source" in source

    def test_fetch_new_source_imports_are_lazy(self):
        source = inspect.getsource(self.mod._fetch_new_source)
        assert "from src.ingestion.source_manager import get_source_by_id" in source

    def test_backfill_ingestion_imports_are_lazy(self):
        source = inspect.getsource(self.mod._backfill_ingestion)
        assert "from src.ingestion.rss_parser import" in source
        assert "from src.ingestion.content_extractor import" in source

    def test_summarize_imports_are_lazy(self):
        source = inspect.getsource(self.mod._summarize_backfilled)
        assert "from src.summarization.summary_processor import" in source

    def test_generate_vault_imports_are_lazy(self):
        source = inspect.getsource(self.mod._generate_vault_notes)
        assert "from src.vault.note_generator import generate_all" in source
