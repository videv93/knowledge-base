"""Git publisher for vault synchronization.

This module handles all git operations for publishing generated vault notes
to the vault repository. It clones/pulls the vault repo, writes generated
notes to the generated/ directory, and commits/pushes changes.
Supports both SSH key and PAT (HTTPS) authentication.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class GitPublisher:
    """Publishes generated vault notes to git repository.

    This is the ONLY module that performs git operations on the vault repository.
    Supports SSH key auth and HTTPS PAT auth.
    """

    def __init__(
        self,
        repo_url: str,
        ssh_key_path: str,
        vault_local_path: str,
        pat: str = "",
    ):
        self.repo_url = repo_url
        self.ssh_key_path = ssh_key_path
        self.pat = pat
        self.vault_local_path = Path(vault_local_path)
        self._use_pat = bool(pat) and repo_url.startswith("https://")

        logger.info(
            f"GitPublisher initialized: repo={repo_url}, "
            f"local_path={vault_local_path}, "
            f"auth={'PAT' if self._use_pat else 'SSH'}"
        )

    def _auth_url(self) -> str:
        """Return repo URL with PAT embedded for HTTPS auth."""
        if not self._use_pat:
            return self.repo_url
        parsed = urlparse(self.repo_url)
        return f"{parsed.scheme}://x-access-token:{self.pat}@{parsed.netloc}{parsed.path}"

    def _configure_git_auth(self) -> None:
        """Configure git authentication (SSH key or PAT)."""
        if self._use_pat:
            return
        os.environ['GIT_SSH_COMMAND'] = (
            f'ssh -i {self.ssh_key_path} '
            f'-o IdentitiesOnly=yes '
            f'-o StrictHostKeyChecking=no'
        )
        logger.debug(f"Configured GIT_SSH_COMMAND with key: {self.ssh_key_path}")

    def _clone_or_pull(self) -> None:
        """Clone repository if it doesn't exist, otherwise pull latest changes."""
        self._configure_git_auth()

        if not self.vault_local_path.exists():
            logger.info(f"Cloning vault repository to {self.vault_local_path}")
            result = subprocess.run(
                ['git', 'clone', self._auth_url(), str(self.vault_local_path)],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Repository cloned successfully")
        else:
            logger.info(f"Pulling latest changes for {self.vault_local_path}")
            result = subprocess.run(
                ['git', '-C', str(self.vault_local_path), 'pull', 'origin', 'main'],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"Repository updated successfully")

    def write_notes(self, notes_by_type: Dict[str, List[Path]]) -> None:
        """Write generated notes to vault's generated/ directory.

        Copies notes from temporary generation location to the vault repository's
        generated/ directory, organized by type (posts/, sources/, authors/).

        Args:
            notes_by_type: Dictionary mapping note type to list of note file paths
                          Example: {"posts": [Path(...), ...], "sources": [...], "authors": [...]}
        """
        generated_dir = self.vault_local_path / "generated"
        generated_dir.mkdir(exist_ok=True)

        total_notes = 0
        for note_type, note_paths in notes_by_type.items():
            type_dir = generated_dir / note_type
            type_dir.mkdir(exist_ok=True)

            for note_path in note_paths:
                # For posts, preserve category subdirectory structure
                if note_type == "posts":
                    # Extract category from parent directory
                    category = note_path.parent.name
                    category_dir = type_dir / category
                    category_dir.mkdir(exist_ok=True)
                    dest_path = category_dir / note_path.name
                else:
                    dest_path = type_dir / note_path.name

                # Copy file content
                dest_path.write_text(note_path.read_text())
                total_notes += 1

        logger.info(f"Wrote {total_notes} notes to {generated_dir}")

    def _has_changes(self) -> bool:
        """Check if there are uncommitted changes in the generated/ directory.

        Returns:
            True if changes exist, False otherwise
        """
        result = subprocess.run(
            ['git', '-C', str(self.vault_local_path), 'status', '--porcelain', 'generated/'],
            capture_output=True,
            text=True,
            check=True,
        )

        has_changes = bool(result.stdout.strip())
        logger.debug(f"Changes detected: {has_changes}")
        return has_changes

    def commit_and_push(
        self,
        run_date: str,
        post_count: int,
        source_count: int,
    ) -> None:
        """Commit and push changes to remote repository.

        Creates a commit with a formatted message and pushes to origin/main.
        If push is rejected due to merge conflict, force pushes since generated
        content is 100% regenerable from database.

        Args:
            run_date: Date of the generation run (YYYY-MM-DD format)
            post_count: Number of posts generated
            source_count: Number of sources generated
        """
        self._configure_git_auth()

        # Set remote URL with auth for push (PAT needs to be in the URL)
        if self._use_pat:
            subprocess.run(
                ['git', '-C', str(self.vault_local_path), 'remote', 'set-url', 'origin', self._auth_url()],
                capture_output=True,
                text=True,
                check=True,
            )

        # Ensure git identity is configured for the repo
        for key, val in [('user.email', 'pipeline@knowledge-base'), ('user.name', 'Knowledge Base Pipeline')]:
            subprocess.run(
                ['git', '-C', str(self.vault_local_path), 'config', key, val],
                capture_output=True, text=True, check=True,
            )

        # Stage changes in generated/ directory
        subprocess.run(
            ['git', '-C', str(self.vault_local_path), 'add', 'generated/'],
            capture_output=True,
            text=True,
            check=True,
        )

        # Create commit with formatted message
        commit_message = (
            f"Generated vault update: {run_date} "
            f"({post_count} posts, {source_count} sources)"
        )
        subprocess.run(
            ['git', '-C', str(self.vault_local_path), 'commit', '-m', commit_message],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"Created commit: {commit_message}")

        # Attempt to push
        try:
            subprocess.run(
                ['git', '-C', str(self.vault_local_path), 'push', 'origin', 'HEAD'],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info("Pushed changes successfully")
        except subprocess.CalledProcessError as e:
            # If push rejected, force push (generated content is regenerable)
            if "rejected" in e.stderr.lower():
                logger.warning(
                    "Push rejected due to merge conflict - force pushing "
                    "(regenerable content)"
                )
                subprocess.run(
                    ['git', '-C', str(self.vault_local_path), 'push', '--force', 'origin', 'main'],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.warning("Force push completed successfully")
            else:
                raise

    def publish(
        self,
        notes_by_type: Dict[str, List[Path]],
        run_date: str,
        post_count: int,
        source_count: int,
    ) -> bool:
        """Orchestrate the full publish workflow.

        Clones/pulls repository, writes notes, commits and pushes changes.
        Skips commit if no changes detected (idempotency).

        Args:
            notes_by_type: Dictionary mapping note type to list of note file paths
            run_date: Date of the generation run (YYYY-MM-DD format)
            post_count: Number of posts generated
            source_count: Number of sources generated

        Returns:
            True if changes were committed and pushed, False if no changes
        """
        try:
            logger.info("Starting vault publish workflow")

            # Step 1: Clone or pull repository
            self._clone_or_pull()

            # Step 2: Write generated notes
            self.write_notes(notes_by_type)

            # Step 3: Check for changes
            if not self._has_changes():
                logger.info("No changes detected - skipping commit")
                return False

            # Step 4: Commit and push
            self.commit_and_push(run_date, post_count, source_count)

            logger.info("Vault publish workflow completed successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(
                f"Git operation failed: {e.cmd}\n"
                f"Return code: {e.returncode}\n"
                f"Stderr: {e.stderr}"
            )
            raise
        except Exception as e:
            logger.error(f"Vault publish failed: {e}")
            raise
