"""Tests for dags/vault_regen_dag.py."""

import importlib.util
import inspect
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_dags_dir = Path(__file__).resolve().parents[2] / "dags"


def _load_vault_regen_dag():
    """Load vault_regen_dag module with mocked airflow dependencies.

    Captures DAG constructor args and operator instantiations for structural testing.
    Returns (module, dag_mock, operators_created, rshift_calls).
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
            "vault_regen_dag_test", _dags_dir / "vault_regen_dag.py"
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


class TestVaultRegenDagStructure:
    """Tests for the vault_regen_ondemand DAG structure and task dependencies."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, self.dag_ctor, self.operators, self.rshift_calls = _load_vault_regen_dag()

    def test_dag_loads_without_errors(self):
        assert self.mod is not None

    def test_dag_id_is_vault_regen_ondemand(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("dag_id") == "vault_regen_ondemand"

    def test_schedule_is_none(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("schedule") is None

    def test_dag_has_expected_task_ids(self):
        expected = {
            "clone_or_pull_vault",
            "generate_all_notes",
            "validate_notes",
            "commit_and_push",
        }
        assert set(self.operators.keys()) == expected

    def test_task_dependency_chain(self):
        """Verify >> chain: clone → generate → validate → commit."""
        expected_chain = [
            ("clone_or_pull_vault", "generate_all_notes"),
            ("generate_all_notes", "validate_notes"),
            ("validate_notes", "commit_and_push"),
        ]
        assert self.rshift_calls == expected_chain

    def test_tags_include_expected(self):
        dag_kwargs = self.dag_ctor.call_args
        tags = dag_kwargs.kwargs.get("tags", [])
        assert "knowledge-base" in tags
        assert "vault" in tags
        assert "regeneration" in tags

    def test_max_active_runs_is_one(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("max_active_runs") == 1

    def test_uses_default_args(self):
        dag_kwargs = self.dag_ctor.call_args
        args = dag_kwargs.kwargs.get("default_args", {})
        assert args["retries"] == 3
        assert args["owner"] == "knowledge-base"

    def test_catchup_is_false(self):
        dag_kwargs = self.dag_ctor.call_args
        assert dag_kwargs.kwargs.get("catchup") is False

    def test_all_tasks_are_python_operators(self):
        for task_id, task in self.operators.items():
            assert task.python_callable is not None, f"{task_id} should have a python_callable"


class TestVaultRegenCallables:
    """Tests that each callable uses lazy imports for src.* modules."""

    @pytest.fixture(autouse=True)
    def load_dag(self):
        self.mod, _, self.operators, _ = _load_vault_regen_dag()

    def test_clone_or_pull_vault_lazy_imports(self):
        source = inspect.getsource(self.operators["clone_or_pull_vault"].python_callable)
        assert "src.common.config" in source
        assert "src.vault.git_publisher" in source

    def test_generate_all_notes_lazy_imports(self):
        source = inspect.getsource(self.operators["generate_all_notes"].python_callable)
        assert "src.common.config" in source
        assert "src.vault.note_generator" in source

    def test_validate_notes_lazy_imports(self):
        source = inspect.getsource(self.operators["validate_notes"].python_callable)
        assert "src.common.config" in source
        assert "src.vault.note_validator" in source

    def test_commit_and_push_lazy_imports(self):
        source = inspect.getsource(self.operators["commit_and_push"].python_callable)
        assert "src.common.config" in source
        assert "src.vault.git_publisher" in source

    def test_generate_all_notes_clears_generated_dir(self):
        source = inspect.getsource(self.operators["generate_all_notes"].python_callable)
        assert "shutil.rmtree" in source

    def test_commit_and_push_pulls_xcom_from_generate(self):
        source = inspect.getsource(self.operators["commit_and_push"].python_callable)
        assert "generate_all_notes" in source
        assert "xcom_pull" in source
