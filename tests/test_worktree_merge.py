"""Tests for WorktreeManager merge functionality."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.workspace.git_ops import (
    add,
    checkout,
    commit,
    current_branch,
    rev_parse,
    run_git,
    worktree_list,
)
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.worktree_manager import WorktreeMergeResult, WorktreeManager


class MockEmitter:
    """Records emitted events for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git("init", cwd=repo)
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=repo)
    run_git("commit", "-m", "Initial commit", cwd=repo)
    return repo


@pytest.fixture()
def session_branch(git_repo: Path) -> str:
    """Create and checkout a session branch, returning its name.

    The branch name must not be a git-ref prefix of the worktree branch names
    produced by ``_worktree_branch_name`` (``wt/test-pipe/sess123/<id>``).
    We use a ``session/`` prefix to keep it in a separate ref namespace.
    """
    branch_name = "session/test-pipe/sess123"
    run_git("checkout", "-b", branch_name, cwd=git_repo)
    return branch_name


@pytest.fixture()
def emitter() -> MockEmitter:
    return MockEmitter()


@pytest.fixture()
def manager(
    git_repo: Path,
    session_branch: str,
    emitter: MockEmitter,
) -> WorktreeManager:
    base_sha = rev_parse("HEAD", cwd=git_repo)
    repo_ctx = RepoContext(
        name="project",
        path=git_repo,
        branch=session_branch,
        base_sha=base_sha,
    )
    return WorktreeManager(
        repo_contexts={"project": repo_ctx},
        session_id="sess123",
        pipeline_name="test-pipe",
        branch_prefix="wt/",
        event_emitter=emitter,
    )


def _create_worktree_with_file(
    manager: WorktreeManager,
    branch_id: str,
    filename: str,
    content: str,
) -> None:
    """Helper: create a worktree, write a file, and commit it."""
    wt_contexts = manager.create_worktrees(branch_id)
    wt_ctx = wt_contexts["project"]
    wt_path = wt_ctx.worktree_path
    assert wt_path is not None

    (wt_path / filename).write_text(content)
    add([filename], cwd=wt_path)
    commit(
        f"Add {filename} from {branch_id}",
        author="Agent <agent@test.com>",
        cwd=wt_path,
    )


def _create_worktree_edit_file(
    manager: WorktreeManager,
    branch_id: str,
    filename: str,
    content: str,
) -> None:
    """Helper: create a worktree, edit an existing file, and commit."""
    wt_contexts = manager.create_worktrees(branch_id)
    wt_ctx = wt_contexts["project"]
    wt_path = wt_ctx.worktree_path
    assert wt_path is not None

    (wt_path / filename).write_text(content)
    add([filename], cwd=wt_path)
    commit(
        f"Edit {filename} from {branch_id}",
        author="Agent <agent@test.com>",
        cwd=wt_path,
    )


class TestCleanMerge:
    """Two branches edit different files -- merge succeeds with both changes."""

    def test_clean_merge(
        self,
        manager: WorktreeManager,
        git_repo: Path,
        session_branch: str,
    ) -> None:
        # Agent A adds file_a.txt
        _create_worktree_with_file(manager, "agent-a", "file_a.txt", "from agent A\n")
        # Agent B adds file_b.txt
        _create_worktree_with_file(manager, "agent-b", "file_b.txt", "from agent B\n")

        result = manager.merge_worktrees(["agent-a", "agent-b"])

        assert result.success is True
        assert result.conflicts == {}
        assert "project" in result.merged_shas

        # Verify the session branch has both files
        checkout(session_branch, cwd=git_repo)
        assert (git_repo / "file_a.txt").read_text() == "from agent A\n"
        assert (git_repo / "file_b.txt").read_text() == "from agent B\n"


class TestMergeConflictSurfaced:
    """Two branches edit same file -- conflict details serialized in result."""

    def test_merge_conflict_surfaced(
        self,
        manager: WorktreeManager,
        git_repo: Path,
    ) -> None:
        # Agent A edits README.md
        _create_worktree_edit_file(
            manager, "agent-a", "README.md", "# Agent A version\n"
        )
        # Agent B edits the same README.md
        _create_worktree_edit_file(
            manager, "agent-b", "README.md", "# Agent B version\n"
        )

        result = manager.merge_worktrees(["agent-a", "agent-b"])

        assert result.success is False
        assert "project" in result.conflicts

        conflict_info = result.conflicts["project"]
        assert "conflicting_files" in conflict_info
        assert "README.md" in conflict_info["conflicting_files"]
        assert "conflicts" in conflict_info
        # The conflict markers dict should contain the file with markers
        assert "README.md" in conflict_info["conflicts"]
        conflict_text = conflict_info["conflicts"]["README.md"]
        assert "<<<<<<<" in conflict_text or "=======" in conflict_text


class TestWorktreeCleanupOnSuccess:
    """After successful merge, worktree directories are removed."""

    def test_worktree_cleanup_on_success(
        self,
        manager: WorktreeManager,
        git_repo: Path,
    ) -> None:
        _create_worktree_with_file(manager, "agent-a", "file_a.txt", "A\n")
        _create_worktree_with_file(manager, "agent-b", "file_b.txt", "B\n")

        # Grab the worktree paths before merge
        wt_base = git_repo / ".orchestra" / "worktrees" / "sess123"
        wt_a = wt_base / "agent-a"
        wt_b = wt_base / "agent-b"
        assert wt_a.exists()
        assert wt_b.exists()

        result = manager.merge_worktrees(["agent-a", "agent-b"])
        assert result.success is True

        # Worktree directories should be removed
        assert not wt_a.exists()
        assert not wt_b.exists()

        # git worktree list should not contain either worktree
        wt_lines = worktree_list(cwd=git_repo)
        wt_text = "\n".join(wt_lines)
        assert str(wt_a) not in wt_text
        assert str(wt_b) not in wt_text


class TestWorktreePreservedOnFailure:
    """On merge conflict, worktree directories are preserved."""

    def test_worktree_preserved_on_failure(
        self,
        manager: WorktreeManager,
        git_repo: Path,
    ) -> None:
        _create_worktree_edit_file(
            manager, "agent-a", "README.md", "# Agent A\n"
        )
        _create_worktree_edit_file(
            manager, "agent-b", "README.md", "# Agent B\n"
        )

        # Worktree paths
        wt_base = git_repo / ".orchestra" / "worktrees" / "sess123"
        wt_a = wt_base / "agent-a"
        wt_b = wt_base / "agent-b"
        assert wt_a.exists()
        assert wt_b.exists()

        result = manager.merge_worktrees(["agent-a", "agent-b"])
        assert result.success is False

        # Worktree directories should still exist
        assert wt_a.exists()
        assert wt_b.exists()


class TestMergeResultOnSessionBranch:
    """After merge, session branch HEAD contains changes from both agents."""

    def test_merge_result_on_session_branch(
        self,
        manager: WorktreeManager,
        git_repo: Path,
        session_branch: str,
    ) -> None:
        _create_worktree_with_file(manager, "agent-a", "file_a.txt", "alpha\n")
        _create_worktree_with_file(manager, "agent-b", "file_b.txt", "beta\n")

        result = manager.merge_worktrees(["agent-a", "agent-b"])
        assert result.success is True

        # Ensure we are on the session branch
        branch = current_branch(cwd=git_repo)
        assert branch == session_branch

        # The merged SHA should be the current HEAD
        head_sha = rev_parse("HEAD", cwd=git_repo)
        assert result.merged_shas["project"] == head_sha

        # Both files should be reachable from HEAD
        assert (git_repo / "file_a.txt").read_text() == "alpha\n"
        assert (git_repo / "file_b.txt").read_text() == "beta\n"

        # README.md (from initial commit) should still be present
        assert (git_repo / "README.md").read_text() == "# Hello\n"
