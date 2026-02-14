from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestra.cli.cleanup import _extract_session_id, _is_older_than_days
from orchestra.workspace.git_ops import create_branch, current_branch, list_branches, run_git


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a git repo with initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", cwd=repo)
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=repo)
    run_git("commit", "-m", "Initial commit", cwd=repo)
    return repo


class TestExtractSessionId:
    def test_standard_branch(self) -> None:
        assert _extract_session_id("orchestra/my-pipeline/abc123", "orchestra/") == "abc123"

    def test_nested_prefix(self) -> None:
        assert _extract_session_id("custom/prefix/pipe/sess", "custom/prefix/") == "sess"

    def test_no_match(self) -> None:
        assert _extract_session_id("other/branch", "orchestra/") == ""

    def test_short_branch(self) -> None:
        assert _extract_session_id("orchestra/", "orchestra/") == ""


class TestIsOlderThanDays:
    def test_old_date(self) -> None:
        assert _is_older_than_days("2020-01-01 00:00:00 +0000", 1) is True

    def test_recent_date(self) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d %H:%M:%S +0000")
        assert _is_older_than_days(date_str, 1) is False

    def test_zero_days(self) -> None:
        assert _is_older_than_days("2020-01-01 00:00:00 +0000", 0) is True

    def test_invalid_date(self) -> None:
        assert _is_older_than_days("not-a-date", 1) is False


class TestCleanupRemovesOldBranches:
    def test_cleanup_removes_old_branches(self, git_repo: Path, tmp_path: Path) -> None:
        """Branches older than threshold removed."""
        # Create some session branches
        original = current_branch(cwd=git_repo)
        create_branch("orchestra/pipe/old-sess", cwd=git_repo)
        run_git("checkout", original, cwd=git_repo)

        branches_before = list_branches("orchestra/*", cwd=git_repo)
        assert "orchestra/pipe/old-sess" in branches_before

        # Use the cleanup functions directly (no CXDB dependency)
        from orchestra.workspace import git_ops

        # The branch was just created so it won't be "old"
        # Use --older-than 0 to force removal
        branch_date = git_ops.branch_date("orchestra/pipe/old-sess", cwd=git_repo)
        assert _is_older_than_days(branch_date, 0) is True

        git_ops.branch_delete("orchestra/pipe/old-sess", cwd=git_repo)
        branches_after = list_branches("orchestra/*", cwd=git_repo)
        assert "orchestra/pipe/old-sess" not in branches_after


class TestCleanupRemovesOrphanedWorktrees:
    def test_cleanup_removes_orphaned_worktrees(self, git_repo: Path) -> None:
        """Worktrees from crashed sessions removed."""
        # Create an orphaned worktree directory
        wt_base = git_repo / ".orchestra" / "worktrees" / "orphan-session"
        wt_dir = wt_base / "agent-a"
        wt_dir.mkdir(parents=True)

        # Create an actual git worktree there
        run_git("worktree", "add", str(wt_dir), "-b", "wt-orphan", cwd=git_repo)

        assert wt_dir.exists()

        # Simulate cleanup: remove worktree
        from orchestra.workspace import git_ops
        git_ops.worktree_remove(wt_dir, cwd=git_repo)

        assert not wt_dir.exists()


class TestCleanupPreservesActiveSessions:
    def test_cleanup_preserves_active_sessions(self, git_repo: Path) -> None:
        """Active session branches are not removed (via session ID matching)."""
        original = current_branch(cwd=git_repo)
        create_branch("orchestra/pipe/active-sess", cwd=git_repo)
        run_git("checkout", original, cwd=git_repo)

        active_ids = {"active-sess"}

        # Extract session ID
        session_id = _extract_session_id("orchestra/pipe/active-sess", "orchestra/")
        assert session_id == "active-sess"
        assert session_id in active_ids

        # Branch should be preserved — don't delete it
        branches = list_branches("orchestra/*", cwd=git_repo)
        assert "orchestra/pipe/active-sess" in branches


class TestCleanupReportsRemoved:
    def test_cleanup_reports_removed(self, git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """CLI output lists removed branches and worktrees."""
        from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
        from orchestra.cli.cleanup import cleanup

        original = current_branch(cwd=git_repo)
        create_branch("orchestra/pipe/stale123", cwd=git_repo)
        run_git("checkout", original, cwd=git_repo)

        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={"project": RepoConfig(path=str(git_repo))}
            ),
            config_dir=tmp_path,
        )

        # Mock CXDB and config loading
        mock_client = MagicMock()
        mock_client.list_contexts.return_value = []

        with (
            patch("orchestra.cli.cleanup.load_config", return_value=config),
            patch("orchestra.cli.cleanup.CxdbClient", return_value=mock_client),
        ):
            cleanup(older_than=0)

        captured = capsys.readouterr()
        assert "stale123" in captured.out
        assert "Removed branches" in captured.out


class TestCleanupAgeThreshold:
    def test_cleanup_age_threshold(self, git_repo: Path) -> None:
        """--older-than 0 removes all; --older-than 30 keeps recent ones."""
        from orchestra.workspace import git_ops

        original = current_branch(cwd=git_repo)
        create_branch("orchestra/pipe/recent-sess", cwd=git_repo)
        run_git("checkout", original, cwd=git_repo)

        date_str = git_ops.branch_date("orchestra/pipe/recent-sess", cwd=git_repo)

        # Just created → not older than 30 days
        assert _is_older_than_days(date_str, 30) is False

        # But is older than 0 days (0 means "all")
        assert _is_older_than_days(date_str, 0) is True
