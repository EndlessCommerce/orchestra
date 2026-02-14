"""Tests for WorktreeManager: creation, isolation, merge, and cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from orchestra.workspace import git_ops
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.worktree_manager import WorktreeManager


SESSION_ID = "test-session"
PIPELINE_NAME = "test-pipeline"
BRANCH_PREFIX = "orchestra/wt/"
SESSION_BRANCH = "orchestra/test-pipeline/test-session"


class MockEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, **data: object) -> None:
        self.events.append((event_type, data))


def _run(cmd: str, cwd: Path) -> str:
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit and session branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git init", cwd=repo)
    _run("git config user.email test@test.com", cwd=repo)
    _run("git config user.name Test", cwd=repo)

    # Initial commit on main so we have a valid HEAD
    (repo / "README.md").write_text("init\n")
    _run("git add .", cwd=repo)
    _run("git commit -m 'Initial commit'", cwd=repo)

    # Create the session branch
    _run(f"git checkout -b {SESSION_BRANCH}", cwd=repo)

    return repo


@pytest.fixture()
def repo_ctx(git_repo: Path) -> RepoContext:
    base_sha = git_ops.rev_parse("HEAD", cwd=git_repo)
    return RepoContext(
        name="project",
        path=git_repo,
        branch=SESSION_BRANCH,
        base_sha=base_sha,
    )


@pytest.fixture()
def emitter() -> MockEmitter:
    return MockEmitter()


@pytest.fixture()
def manager(repo_ctx: RepoContext, emitter: MockEmitter) -> WorktreeManager:
    return WorktreeManager(
        repo_contexts={"project": repo_ctx},
        session_id=SESSION_ID,
        pipeline_name=PIPELINE_NAME,
        branch_prefix=BRANCH_PREFIX,
        event_emitter=emitter,
    )


class TestWorktreeCreation:
    def test_worktree_created_for_parallel(
        self, manager: WorktreeManager, repo_ctx: RepoContext
    ) -> None:
        """Create worktrees for 2 branch_ids -- both directories must exist."""
        ctx_a = manager.create_worktrees("agent-a")
        ctx_b = manager.create_worktrees("agent-b")

        wt_a = ctx_a["project"].worktree_path
        wt_b = ctx_b["project"].worktree_path

        assert wt_a is not None and wt_a.exists()
        assert wt_b is not None and wt_b.exists()
        # They must be distinct directories
        assert wt_a != wt_b

    def test_worktree_path(
        self, manager: WorktreeManager, repo_ctx: RepoContext
    ) -> None:
        """Worktrees live at .orchestra/worktrees/{session_id}/{branch_id}."""
        ctx = manager.create_worktrees("step-1")
        wt_path = ctx["project"].worktree_path

        expected = (
            repo_ctx.path / ".orchestra" / "worktrees" / SESSION_ID / "step-1"
        )
        assert wt_path == expected


class TestWorktreeIsolation:
    def test_worktree_isolation(
        self, manager: WorktreeManager
    ) -> None:
        """A file written in worktree A must NOT be visible in worktree B."""
        ctx_a = manager.create_worktrees("branch-a")
        ctx_b = manager.create_worktrees("branch-b")

        wt_a = ctx_a["project"].worktree_path
        wt_b = ctx_b["project"].worktree_path
        assert wt_a is not None and wt_b is not None

        # Write a file only in worktree A
        (wt_a / "only_in_a.txt").write_text("secret\n")

        assert (wt_a / "only_in_a.txt").exists()
        assert not (wt_b / "only_in_a.txt").exists()


class TestPerTurnCommitInWorktree:
    def test_per_turn_commits_in_worktree(
        self, manager: WorktreeManager, repo_ctx: RepoContext
    ) -> None:
        """A commit inside a worktree lands on the worktree branch, not session."""
        ctx = manager.create_worktrees("agent-x")
        wt_ctx = ctx["project"]
        wt_path = wt_ctx.worktree_path
        assert wt_path is not None

        # Record session HEAD before the worktree commit
        session_head_before = git_ops.rev_parse("HEAD", cwd=repo_ctx.path)

        # Make a commit inside the worktree
        (wt_path / "agent_work.txt").write_text("work\n")
        git_ops.add(["agent_work.txt"], cwd=wt_path)
        git_ops.commit(
            "Agent turn 1",
            author="Agent <agent@local>",
            cwd=wt_path,
        )

        # The worktree branch should have advanced
        wt_head = git_ops.rev_parse("HEAD", cwd=wt_path)
        assert wt_head != session_head_before

        # The session branch should NOT have moved
        session_head_after = git_ops.rev_parse(
            SESSION_BRANCH, cwd=repo_ctx.path
        )
        assert session_head_after == session_head_before


class TestMergeAndSequential:
    def test_sequential_no_worktree(
        self,
        manager: WorktreeManager,
        repo_ctx: RepoContext,
        emitter: MockEmitter,
    ) -> None:
        """After a successful fan-in merge, the session branch has the work and
        the worktree branches are cleaned up -- subsequent operations use the
        session branch directly."""
        # Create two worktrees and commit different files in each
        ctx_a = manager.create_worktrees("par-a")
        ctx_b = manager.create_worktrees("par-b")

        wt_a = ctx_a["project"].worktree_path
        wt_b = ctx_b["project"].worktree_path
        assert wt_a is not None and wt_b is not None

        (wt_a / "file_a.txt").write_text("from a\n")
        git_ops.add(["file_a.txt"], cwd=wt_a)
        git_ops.commit("Add file_a", author="Agent <a@local>", cwd=wt_a)

        (wt_b / "file_b.txt").write_text("from b\n")
        git_ops.add(["file_b.txt"], cwd=wt_b)
        git_ops.commit("Add file_b", author="Agent <b@local>", cwd=wt_b)

        # Merge both worktrees back into session branch
        result = manager.merge_worktrees(["par-a", "par-b"])
        assert result.success is True
        assert len(result.conflicts) == 0
        assert "project" in result.merged_shas

        # Session branch now has both files
        assert (repo_ctx.path / "file_a.txt").exists()
        assert (repo_ctx.path / "file_b.txt").exists()

        # Worktree directories should be cleaned up
        assert not wt_a.exists()
        assert not wt_b.exists()

        # A WorktreeMerged event was emitted
        merged_events = [e for e in emitter.events if e[0] == "WorktreeMerged"]
        assert len(merged_events) == 1

        # Current branch in the main repo is back to session branch
        branch = git_ops.current_branch(cwd=repo_ctx.path)
        assert branch == SESSION_BRANCH
