"""Tests for vault git publisher — clone/pull, write notes, commit/push, SSH config."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.vault.git_publisher import GitPublisher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def publisher(tmp_path):
    """Create a GitPublisher with a temporary vault path."""
    return GitPublisher(
        repo_url="git@github.com:user/repo.git",
        ssh_key_path="/path/to/ssh_key",
        vault_local_path=str(tmp_path / "vault-clone"),
    )


@pytest.fixture
def publisher_with_clone(tmp_path):
    """Create a GitPublisher where the local vault directory already exists."""
    vault_path = tmp_path / "vault-clone"
    vault_path.mkdir()
    return GitPublisher(
        repo_url="git@github.com:user/repo.git",
        ssh_key_path="/path/to/ssh_key",
        vault_local_path=str(vault_path),
    )


@pytest.fixture
def sample_notes(tmp_path):
    """Create sample note files and return notes_by_type dict."""
    src_dir = tmp_path / "source-notes"

    # Posts with category subdirectory
    post_dir = src_dir / "posts" / "data-engineering"
    post_dir.mkdir(parents=True)
    post1 = post_dir / "kafka-streams.md"
    post1.write_text("---\nuid: 1\n---\n# Kafka Streams\n")
    post2 = post_dir / "flink-intro.md"
    post2.write_text("---\nuid: 2\n---\n# Flink Intro\n")

    # Sources
    source_dir = src_dir / "sources"
    source_dir.mkdir(parents=True)
    source1 = source_dir / "engineering-blog.md"
    source1.write_text("---\nname: Engineering Blog\n---\n# Engineering Blog\n")

    # Authors
    author_dir = src_dir / "authors"
    author_dir.mkdir(parents=True)
    author1 = author_dir / "jane-doe.md"
    author1.write_text("---\nname: Jane Doe\n---\n# Jane Doe\n")

    return {
        "posts": [post1, post2],
        "sources": [source1],
        "authors": [author1],
    }


# ---------------------------------------------------------------------------
# _configure_git_ssh
# ---------------------------------------------------------------------------


class TestConfigureGitSsh:
    def test_sets_git_ssh_command_env_var(self, publisher, monkeypatch):
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)

        publisher._configure_git_ssh()

        import os

        ssh_cmd = os.environ["GIT_SSH_COMMAND"]
        assert "/path/to/ssh_key" in ssh_cmd
        assert "IdentitiesOnly=yes" in ssh_cmd
        assert "StrictHostKeyChecking=no" in ssh_cmd

    def test_uses_configured_key_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
        custom_key = "/custom/key/id_rsa"
        pub = GitPublisher(
            repo_url="git@github.com:user/repo.git",
            ssh_key_path=custom_key,
            vault_local_path=str(tmp_path / "vault"),
        )

        pub._configure_git_ssh()

        import os

        assert custom_key in os.environ["GIT_SSH_COMMAND"]


# ---------------------------------------------------------------------------
# _clone_or_pull
# ---------------------------------------------------------------------------


class TestCloneOrPull:
    @patch("subprocess.run")
    def test_clones_when_directory_does_not_exist(self, mock_run, publisher):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher._clone_or_pull()

        # First call is git clone
        clone_call = mock_run.call_args_list[0]
        assert "clone" in clone_call[0][0]
        assert publisher.repo_url in clone_call[0][0]
        assert str(publisher.vault_local_path) in clone_call[0][0]

    @patch("subprocess.run")
    def test_pulls_when_directory_exists(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone._clone_or_pull()

        pull_call = mock_run.call_args_list[0]
        assert "pull" in pull_call[0][0]
        assert "origin" in pull_call[0][0]
        assert "main" in pull_call[0][0]

    @patch("subprocess.run")
    def test_configures_ssh_before_git_operation(self, mock_run, publisher, monkeypatch):
        monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher._clone_or_pull()

        import os

        assert "GIT_SSH_COMMAND" in os.environ

    @patch("subprocess.run")
    def test_clone_failure_raises(self, mock_run, publisher):
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git clone", stderr="fatal: repository not found"
        )

        with pytest.raises(subprocess.CalledProcessError):
            publisher._clone_or_pull()


# ---------------------------------------------------------------------------
# write_notes
# ---------------------------------------------------------------------------


class TestWriteNotes:
    def test_copies_notes_to_generated_directory(self, publisher_with_clone, sample_notes):
        publisher_with_clone.write_notes(sample_notes)

        generated_dir = publisher_with_clone.vault_local_path / "generated"
        assert (generated_dir / "posts" / "data-engineering" / "kafka-streams.md").exists()
        assert (generated_dir / "posts" / "data-engineering" / "flink-intro.md").exists()
        assert (generated_dir / "sources" / "engineering-blog.md").exists()
        assert (generated_dir / "authors" / "jane-doe.md").exists()

    def test_preserves_post_category_subdirectory(self, publisher_with_clone, sample_notes):
        publisher_with_clone.write_notes(sample_notes)

        generated_dir = publisher_with_clone.vault_local_path / "generated"
        post_path = generated_dir / "posts" / "data-engineering" / "kafka-streams.md"
        assert post_path.exists()
        assert "Kafka Streams" in post_path.read_text()

    def test_creates_generated_directory_if_missing(self, publisher_with_clone, sample_notes):
        generated_dir = publisher_with_clone.vault_local_path / "generated"
        assert not generated_dir.exists()

        publisher_with_clone.write_notes(sample_notes)

        assert generated_dir.exists()

    def test_empty_notes_dict_creates_no_files(self, publisher_with_clone):
        publisher_with_clone.write_notes({})

        generated_dir = publisher_with_clone.vault_local_path / "generated"
        assert generated_dir.exists()
        # Only the generated/ dir itself, no subdirectories
        assert list(generated_dir.iterdir()) == []

    def test_preserves_file_content(self, publisher_with_clone, sample_notes):
        publisher_with_clone.write_notes(sample_notes)

        generated_dir = publisher_with_clone.vault_local_path / "generated"
        source_content = (generated_dir / "sources" / "engineering-blog.md").read_text()
        assert "Engineering Blog" in source_content


# ---------------------------------------------------------------------------
# _has_changes
# ---------------------------------------------------------------------------


class TestHasChanges:
    @patch("subprocess.run")
    def test_returns_true_when_changes_exist(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M generated/posts/data-engineering/new-post.md\n",
            stderr="",
        )

        assert publisher_with_clone._has_changes() is True

    @patch("subprocess.run")
    def test_returns_false_when_no_changes(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        assert publisher_with_clone._has_changes() is False

    @patch("subprocess.run")
    def test_runs_git_status_porcelain_on_generated(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone._has_changes()

        cmd = mock_run.call_args[0][0]
        assert "status" in cmd
        assert "--porcelain" in cmd
        assert "generated/" in cmd


# ---------------------------------------------------------------------------
# commit_and_push
# ---------------------------------------------------------------------------


class TestCommitAndPush:
    @patch("subprocess.run")
    def test_stages_generated_directory(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone.commit_and_push("2026-03-02", 47, 211)

        add_call = mock_run.call_args_list[0]
        assert "add" in add_call[0][0]
        assert "generated/" in add_call[0][0]

    @patch("subprocess.run")
    def test_commit_message_format(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone.commit_and_push("2026-03-02", 47, 211)

        commit_call = mock_run.call_args_list[1]
        cmd = commit_call[0][0]
        assert "commit" in cmd
        # Find the -m flag and check the message
        msg_idx = cmd.index("-m") + 1
        assert "Generated vault update: 2026-03-02 (47 posts, 211 sources)" == cmd[msg_idx]

    @patch("subprocess.run")
    def test_pushes_to_origin_main(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone.commit_and_push("2026-03-02", 47, 211)

        push_call = mock_run.call_args_list[2]
        cmd = push_call[0][0]
        assert "push" in cmd
        assert "origin" in cmd
        assert "main" in cmd

    @patch("subprocess.run")
    def test_force_pushes_on_rejected(self, mock_run, publisher_with_clone):
        # add and commit succeed, first push fails with "rejected"
        success = MagicMock(returncode=0, stdout="", stderr="")
        rejected_error = subprocess.CalledProcessError(
            1, "git push", stderr="error: failed to push some refs\nrejected"
        )

        mock_run.side_effect = [success, success, rejected_error, success]

        publisher_with_clone.commit_and_push("2026-03-02", 47, 211)

        force_push_call = mock_run.call_args_list[3]
        cmd = force_push_call[0][0]
        assert "--force" in cmd
        assert "push" in cmd

    @patch("subprocess.run")
    def test_non_rejected_push_error_raises(self, mock_run, publisher_with_clone):
        success = MagicMock(returncode=0, stdout="", stderr="")
        auth_error = subprocess.CalledProcessError(
            128, "git push", stderr="fatal: Authentication failed"
        )

        mock_run.side_effect = [success, success, auth_error]

        with pytest.raises(subprocess.CalledProcessError):
            publisher_with_clone.commit_and_push("2026-03-02", 47, 211)


# ---------------------------------------------------------------------------
# publish (orchestrator)
# ---------------------------------------------------------------------------


class TestPublish:
    @patch("subprocess.run")
    def test_publish_with_changes_returns_true(self, mock_run, publisher_with_clone, sample_notes):
        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if "status" in cmd and "--porcelain" in cmd:
                result.stdout = " M generated/posts/new.md\n"
            return result

        mock_run.side_effect = run_side_effect

        result = publisher_with_clone.publish(sample_notes, "2026-03-02", 47, 211)

        assert result is True

    @patch("subprocess.run")
    def test_publish_with_no_changes_returns_false(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = publisher_with_clone.publish({}, "2026-03-02", 0, 0)

        assert result is False

    @patch("subprocess.run")
    def test_publish_skips_commit_when_no_changes(self, mock_run, publisher_with_clone):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        publisher_with_clone.publish({}, "2026-03-02", 0, 0)

        # Should NOT have a "git commit" call — check actual command lists
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert not any("commit" in cmd for cmd in cmds)

    @patch("subprocess.run")
    def test_publish_calls_pull_write_check_commit(self, mock_run, publisher_with_clone, sample_notes):
        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")
            if "status" in cmd and "--porcelain" in cmd:
                result.stdout = " M generated/posts/new.md\n"
            return result

        mock_run.side_effect = run_side_effect

        publisher_with_clone.publish(sample_notes, "2026-03-02", 4, 1)

        # Verify the sequence: pull, status, add, commit, push
        cmds = [c[0][0] for c in mock_run.call_args_list]
        cmd_types = []
        for cmd in cmds:
            if "pull" in cmd:
                cmd_types.append("pull")
            elif "status" in cmd:
                cmd_types.append("status")
            elif "add" in cmd:
                cmd_types.append("add")
            elif "commit" in cmd:
                cmd_types.append("commit")
            elif "push" in cmd:
                cmd_types.append("push")

        assert "pull" in cmd_types
        assert "status" in cmd_types
        assert "add" in cmd_types
        assert "commit" in cmd_types
        assert "push" in cmd_types

    @patch("subprocess.run")
    def test_publish_git_failure_raises_and_logs(self, mock_run, publisher_with_clone, caplog):
        mock_run.side_effect = subprocess.CalledProcessError(
            128, "git pull", stderr="fatal: repository not found"
        )

        import logging

        with caplog.at_level(logging.ERROR):
            with pytest.raises(subprocess.CalledProcessError):
                publisher_with_clone.publish({}, "2026-03-02", 0, 0)

        assert any("Git operation failed" in record.message for record in caplog.records)

    @patch("subprocess.run")
    def test_publish_force_pushes_on_conflict(self, mock_run, publisher_with_clone, sample_notes):
        def run_side_effect(cmd, **kwargs):
            result = MagicMock(returncode=0, stdout="", stderr="")

            if "status" in cmd and "--porcelain" in cmd:
                result.stdout = " M generated/posts/new.md\n"
                return result

            if "push" in cmd and "--force" not in cmd:
                raise subprocess.CalledProcessError(
                    1, "git push", stderr="rejected"
                )

            return result

        mock_run.side_effect = run_side_effect

        result = publisher_with_clone.publish(sample_notes, "2026-03-02", 4, 1)

        assert result is True
        # Verify force push was called
        all_cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("--force" in cmd for cmd in all_cmds)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    @patch("subprocess.run")
    def test_logs_clone_at_info(self, mock_run, publisher, caplog):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        import logging

        with caplog.at_level(logging.INFO, logger="src.vault.git_publisher"):
            publisher._clone_or_pull()

        assert any("Cloning" in record.message for record in caplog.records)

    @patch("subprocess.run")
    def test_logs_pull_at_info(self, mock_run, publisher_with_clone, caplog):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        import logging

        with caplog.at_level(logging.INFO, logger="src.vault.git_publisher"):
            publisher_with_clone._clone_or_pull()

        assert any("Pulling" in record.message for record in caplog.records)

    @patch("subprocess.run")
    def test_logs_no_changes_at_info(self, mock_run, publisher_with_clone, caplog):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        import logging

        with caplog.at_level(logging.INFO, logger="src.vault.git_publisher"):
            publisher_with_clone.publish({}, "2026-03-02", 0, 0)

        assert any("No changes" in record.message for record in caplog.records)

    @patch("subprocess.run")
    def test_logs_force_push_at_warning(self, mock_run, publisher_with_clone, caplog):
        success = MagicMock(returncode=0, stdout="", stderr="")
        rejected_error = subprocess.CalledProcessError(
            1, "git push", stderr="rejected"
        )
        mock_run.side_effect = [success, success, rejected_error, success]

        import logging

        with caplog.at_level(logging.WARNING, logger="src.vault.git_publisher"):
            publisher_with_clone.commit_and_push("2026-03-02", 47, 211)

        assert any(
            "Force push" in record.message or "force push" in record.message.lower()
            for record in caplog.records
        )


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


class TestPublicApi:
    def test_git_publisher_importable_from_vault(self):
        from src.vault import GitPublisher as GP

        assert GP is not None

    def test_git_publisher_in_all(self):
        from src.vault import __all__

        assert "GitPublisher" in __all__
