"""Tests for workspace snapshot functionality.

Covers WorkspaceManager.get_workspace_snapshot() which returns {repo_name: HEAD_SHA}
for each repo, returning {} when nothing has changed since the last snapshot call.
Also validates the CheckpointSaved event's workspace_snapshot field.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.events.types import CheckpointSaved
from orchestra.workspace.commit_message import DeterministicCommitMessageGenerator
from orchestra.workspace.git_ops import rev_parse, run_git
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.workspace_manager import WorkspaceManager


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _init_git_repo(path: Path) -> None:
    """Initialise a bare-minimum git repo with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    run_git("init", cwd=path)
    run_git("config", "user.email", "test@test.com", cwd=path)
    run_git("config", "user.name", "Test", cwd=path)
    (path / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=path)
    run_git("commit", "-m", "Initial commit", cwd=path)


def _make_commit(repo: Path, filename: str, content: str) -> str:
    """Create a new file, stage, commit, and return the new HEAD SHA."""
    (repo / filename).write_text(content)
    run_git("add", filename, cwd=repo)
    run_git("commit", "-m", f"Add {filename}", cwd=repo)
    return rev_parse("HEAD", cwd=repo)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    return repo


@pytest.fixture()
def emitter() -> RecordingEmitter:
    return RecordingEmitter()


@pytest.fixture()
def commit_gen() -> DeterministicCommitMessageGenerator:
    return DeterministicCommitMessageGenerator()


def _make_manager(
    repos: dict[str, Path],
    emitter: RecordingEmitter,
    commit_gen: DeterministicCommitMessageGenerator,
) -> WorkspaceManager:
    """Build a WorkspaceManager with repo contexts pre-populated (no session branch setup)."""
    repo_configs = {
        name: RepoConfig(path=str(path)) for name, path in repos.items()
    }
    config = OrchestraConfig(
        workspace=WorkspaceConfig(repos=repo_configs),
        config_dir=list(repos.values())[0].parent,
    )
    mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)

    # Directly populate _repo_contexts so we don't need full session setup
    for name, path in repos.items():
        mgr._repo_contexts[name] = RepoContext(
            name=name,
            path=path,
            branch="main",
            base_sha=rev_parse("HEAD", cwd=path),
        )
    return mgr


class TestCheckpointIncludesWorkspaceSnapshot:
    """After a commit changes HEAD, get_workspace_snapshot() returns {repo_name: new_sha}."""

    def test_returns_snapshot_after_commit(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # Make a commit so HEAD advances
        new_sha = _make_commit(git_repo, "new_file.py", "print('hello')\n")

        snapshot = mgr.get_workspace_snapshot()

        assert snapshot == {"project": new_sha}
        assert len(new_sha) == 40

    def test_snapshot_populates_checkpoint_event(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        _make_commit(git_repo, "feature.py", "x = 1\n")
        snapshot = mgr.get_workspace_snapshot()

        # Verify the snapshot can be assigned to CheckpointSaved.workspace_snapshot
        event = CheckpointSaved(
            node_id="test-node",
            workspace_snapshot=snapshot,
        )
        assert event.workspace_snapshot == snapshot
        assert "project" in event.workspace_snapshot
        assert len(event.workspace_snapshot["project"]) == 40


class TestCheckpointSnapshotOnlyOnChange:
    """No commit -> get_workspace_snapshot() returns {} (unchanged)."""

    def test_returns_empty_when_nothing_changed(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # First call captures the initial state
        first_snapshot = mgr.get_workspace_snapshot()
        assert first_snapshot != {}  # First call always returns something

        # Second call with no changes should return {}
        second_snapshot = mgr.get_workspace_snapshot()
        assert second_snapshot == {}

    def test_returns_non_empty_after_new_commit(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # Capture initial state
        mgr.get_workspace_snapshot()

        # Make a commit so HEAD changes
        new_sha = _make_commit(git_repo, "change.txt", "changed\n")

        snapshot = mgr.get_workspace_snapshot()
        assert snapshot == {"project": new_sha}

    def test_alternating_change_no_change(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # First snapshot: initial HEAD
        s1 = mgr.get_workspace_snapshot()
        assert s1 != {}

        # No change
        s2 = mgr.get_workspace_snapshot()
        assert s2 == {}

        # Commit -> change
        sha3 = _make_commit(git_repo, "a.txt", "a\n")
        s3 = mgr.get_workspace_snapshot()
        assert s3 == {"project": sha3}

        # No change again
        s4 = mgr.get_workspace_snapshot()
        assert s4 == {}

        # Another commit -> change
        sha5 = _make_commit(git_repo, "b.txt", "b\n")
        s5 = mgr.get_workspace_snapshot()
        assert s5 == {"project": sha5}


class TestSnapshotPerRepo:
    """Multi-repo workspace -> snapshot has separate SHA for each repo."""

    def test_two_repos_independent_snapshots(
        self,
        tmp_path: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)

        mgr = _make_manager({"alpha": repo_a, "beta": repo_b}, emitter, commit_gen)

        # Advance both repos
        sha_a = _make_commit(repo_a, "file_a.py", "alpha\n")
        sha_b = _make_commit(repo_b, "file_b.py", "beta\n")

        snapshot = mgr.get_workspace_snapshot()

        assert "alpha" in snapshot
        assert "beta" in snapshot
        assert snapshot["alpha"] == sha_a
        assert snapshot["beta"] == sha_b
        assert sha_a != sha_b  # Different repos, different SHAs

    def test_only_changed_repo_triggers_snapshot(
        self,
        tmp_path: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)

        mgr = _make_manager({"alpha": repo_a, "beta": repo_b}, emitter, commit_gen)

        # Capture initial state
        initial = mgr.get_workspace_snapshot()
        assert "alpha" in initial
        assert "beta" in initial

        # Change only repo_a
        new_sha_a = _make_commit(repo_a, "update.py", "updated\n")

        snapshot = mgr.get_workspace_snapshot()
        # The method returns a full snapshot (both repos) whenever any repo changed
        assert snapshot != {}
        assert snapshot["alpha"] == new_sha_a
        assert "beta" in snapshot  # beta SHA still present in full snapshot

    def test_three_repos_all_tracked(
        self,
        tmp_path: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        repos = {}
        shas = {}
        for name in ("frontend", "backend", "infra"):
            repo_path = tmp_path / name
            _init_git_repo(repo_path)
            sha = _make_commit(repo_path, f"{name}.txt", f"{name} content\n")
            repos[name] = repo_path
            shas[name] = sha

        mgr = _make_manager(repos, emitter, commit_gen)

        snapshot = mgr.get_workspace_snapshot()

        assert len(snapshot) == 3
        for name in ("frontend", "backend", "infra"):
            assert snapshot[name] == shas[name]


class TestSnapshotAfterParallel:
    """After worktree merge changes HEAD -> snapshot reflects merged state."""

    def test_snapshot_reflects_merge_commit(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # Capture initial state
        mgr.get_workspace_snapshot()

        # Simulate what happens after a parallel merge: branches are merged
        # into the session branch, advancing HEAD
        pre_merge_sha = rev_parse("HEAD", cwd=git_repo)

        # Create a side branch, commit to it, then merge back (simulating worktree merge)
        original_branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=git_repo)
        run_git("checkout", "-b", "parallel-branch-1", cwd=git_repo)
        _make_commit(git_repo, "parallel_work.py", "parallel code\n")
        run_git("checkout", original_branch, cwd=git_repo)
        run_git("merge", "--no-ff", "parallel-branch-1", "-m", "Merge parallel branch", cwd=git_repo)

        merged_sha = rev_parse("HEAD", cwd=git_repo)
        assert merged_sha != pre_merge_sha

        snapshot = mgr.get_workspace_snapshot()
        assert snapshot == {"project": merged_sha}

    def test_snapshot_after_multiple_merges(
        self,
        git_repo: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        mgr = _make_manager({"project": git_repo}, emitter, commit_gen)

        # Capture initial state
        mgr.get_workspace_snapshot()

        original_branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=git_repo)

        # Create and merge two parallel branches sequentially (as worktree merge does)
        for i in range(2):
            branch_name = f"parallel-branch-{i}"
            run_git("checkout", "-b", branch_name, cwd=git_repo)
            _make_commit(git_repo, f"parallel_{i}.py", f"code {i}\n")
            run_git("checkout", original_branch, cwd=git_repo)
            run_git("merge", "--no-ff", branch_name, "-m", f"Merge branch {i}", cwd=git_repo)

        final_sha = rev_parse("HEAD", cwd=git_repo)
        snapshot = mgr.get_workspace_snapshot()
        assert snapshot == {"project": final_sha}

        # No further changes -> empty
        assert mgr.get_workspace_snapshot() == {}

    def test_multi_repo_parallel_merge(
        self,
        tmp_path: Path,
        emitter: RecordingEmitter,
        commit_gen: DeterministicCommitMessageGenerator,
    ) -> None:
        """Two repos, each with a parallel merge -> snapshot shows both merged SHAs."""
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        _init_git_repo(repo_a)
        _init_git_repo(repo_b)

        mgr = _make_manager({"alpha": repo_a, "beta": repo_b}, emitter, commit_gen)

        # Capture initial state
        mgr.get_workspace_snapshot()

        merged_shas = {}
        for name, repo in [("alpha", repo_a), ("beta", repo_b)]:
            original = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
            run_git("checkout", "-b", f"parallel-{name}", cwd=repo)
            _make_commit(repo, f"{name}_parallel.py", f"{name} parallel\n")
            run_git("checkout", original, cwd=repo)
            run_git("merge", "--no-ff", f"parallel-{name}", "-m", f"Merge {name}", cwd=repo)
            merged_shas[name] = rev_parse("HEAD", cwd=repo)

        snapshot = mgr.get_workspace_snapshot()
        assert snapshot["alpha"] == merged_shas["alpha"]
        assert snapshot["beta"] == merged_shas["beta"]
