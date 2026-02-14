from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestra.config.settings import OrchestraConfig, RepoConfig, WorkspaceConfig
from orchestra.workspace.git_ops import clone, create_branch, run_git
from orchestra.workspace.workspace_manager import WorkspaceManager


@pytest.fixture()
def bare_remote(tmp_path: Path) -> Path:
    """Create a bare remote with an initial commit."""
    source = tmp_path / "source"
    source.mkdir()
    run_git("init", cwd=source)
    run_git("config", "user.email", "test@test.com", cwd=source)
    run_git("config", "user.name", "Test", cwd=source)
    (source / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=source)
    run_git("commit", "-m", "Initial commit", cwd=source)
    bare = tmp_path / "remote.git"
    run_git("clone", "--bare", str(source), str(bare), cwd=tmp_path)
    return bare


@pytest.fixture()
def workspace_repo(tmp_path: Path, bare_remote: Path) -> Path:
    """Clone the bare remote into a workspace directory."""
    target = tmp_path / "workspace" / "project"
    clone(str(bare_remote), target)
    run_git("config", "user.email", "test@test.com", cwd=target)
    run_git("config", "user.name", "Test", cwd=target)
    return target


def _make_manager(
    workspace_repo: Path,
    bare_remote: Path,
    tmp_path: Path,
    push_policy: str = "",
) -> tuple[WorkspaceManager, MagicMock]:
    """Build a WorkspaceManager with a single repo config."""
    emitter = MagicMock()
    config = OrchestraConfig(
        workspace=WorkspaceConfig(
            repos={
                "project": RepoConfig(
                    path=str(workspace_repo),
                    remote=str(bare_remote),
                    push=push_policy,
                )
            }
        ),
        config_dir=tmp_path,
    )
    commit_gen = MagicMock()
    mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
    return mgr, emitter


class TestEffectivePushPolicy:
    def test_default_push_with_remote(self) -> None:
        """Remote set, no push → on_completion."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git")
        assert config.effective_push_policy == "on_completion"

    def test_default_push_without_remote(self) -> None:
        """No remote → never."""
        config = RepoConfig(path="/tmp/repo")
        assert config.effective_push_policy == "never"

    def test_explicit_push_override(self) -> None:
        """Explicit push: never with remote → never."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git", push="never")
        assert config.effective_push_policy == "never"

    def test_explicit_on_checkpoint(self) -> None:
        """Explicit push: on_checkpoint."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git", push="on_checkpoint")
        assert config.effective_push_policy == "on_checkpoint"

    def test_explicit_on_completion_without_remote(self) -> None:
        """Explicit push: on_completion even without remote (user knows best)."""
        config = RepoConfig(path="/tmp/repo", push="on_completion")
        assert config.effective_push_policy == "on_completion"


class TestPushOnCompletion:
    def test_push_on_completion(self, workspace_repo: Path, bare_remote: Path, tmp_path: Path) -> None:
        """Pipeline succeeds → session branch pushed to remote."""
        mgr, emitter = _make_manager(workspace_repo, bare_remote, tmp_path)
        mgr.setup_session("test-pipe", "abc123")

        # Make a commit on the session branch
        (workspace_repo / "new.txt").write_text("new\n")
        run_git("add", "new.txt", cwd=workspace_repo)
        run_git("commit", "-m", "agent change", cwd=workspace_repo)

        mgr.push_session_branches("on_completion")

        # Verify remote has the session branch
        remote_branches = run_git("branch", cwd=bare_remote)
        assert "orchestra/test-pipe/abc123" in remote_branches

        # Verify event emitted
        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "SessionBranchPushed" in event_types

    def test_no_push_on_pipeline_failure(self, workspace_repo: Path, bare_remote: Path, tmp_path: Path) -> None:
        """Pipeline fails → no push (caller doesn't call push_session_branches)."""
        mgr, emitter = _make_manager(workspace_repo, bare_remote, tmp_path)
        mgr.setup_session("test-pipe", "def456")

        # Don't call push_session_branches — simulates pipeline failure
        # Verify remote does NOT have the session branch
        remote_branches = run_git("branch", cwd=bare_remote)
        assert "orchestra/test-pipe/def456" not in remote_branches

    def test_push_failure_non_fatal(self, workspace_repo: Path, bare_remote: Path, tmp_path: Path) -> None:
        """Push fails (bad remote) → warning logged, no exception raised."""
        mgr, emitter = _make_manager(workspace_repo, bare_remote, tmp_path)
        mgr.setup_session("test-pipe", "fail123")

        # Break the origin remote so push will fail
        run_git("remote", "set-url", "origin", "/nonexistent/remote.git", cwd=workspace_repo)

        # Should not raise — push failures are non-fatal
        mgr.push_session_branches("on_completion")

        # Verify SessionBranchPushFailed event emitted
        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "SessionBranchPushFailed" in event_types

    def test_multi_repo_push(self, tmp_path: Path) -> None:
        """2 repos with on_completion → both pushed."""
        # Create 2 bare remotes and clones
        repos_config = {}
        for name in ("backend", "frontend"):
            source = tmp_path / f"src-{name}"
            source.mkdir()
            run_git("init", cwd=source)
            run_git("config", "user.email", "test@test.com", cwd=source)
            run_git("config", "user.name", "Test", cwd=source)
            (source / "README.md").write_text(f"# {name}\n")
            run_git("add", "README.md", cwd=source)
            run_git("commit", "-m", "Initial commit", cwd=source)

            bare = tmp_path / f"{name}-remote.git"
            run_git("clone", "--bare", str(source), str(bare), cwd=tmp_path)

            workspace = tmp_path / "workspace" / name
            clone(str(bare), workspace)
            run_git("config", "user.email", "test@test.com", cwd=workspace)
            run_git("config", "user.name", "Test", cwd=workspace)

            repos_config[name] = RepoConfig(
                path=str(workspace),
                remote=str(bare),
            )

        emitter = MagicMock()
        config = OrchestraConfig(
            workspace=WorkspaceConfig(repos=repos_config),
            config_dir=tmp_path,
        )
        commit_gen = MagicMock()
        mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
        mgr.setup_session("multi", "m123")

        mgr.push_session_branches("on_completion")

        # Both repos should have pushed
        push_events = [
            call for call in emitter.emit.call_args_list
            if call.args[0] == "SessionBranchPushed"
        ]
        assert len(push_events) == 2
        pushed_repos = {call.kwargs["repo_name"] for call in push_events}
        assert pushed_repos == {"backend", "frontend"}

    def test_push_never_skips(self, workspace_repo: Path, bare_remote: Path, tmp_path: Path) -> None:
        """push: never → no push even with remote configured."""
        mgr, emitter = _make_manager(workspace_repo, bare_remote, tmp_path, push_policy="never")
        mgr.setup_session("test-pipe", "never123")

        mgr.push_session_branches("on_completion")

        # No push events — policy doesn't match
        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "SessionBranchPushed" not in event_types
        assert "SessionBranchPushFailed" not in event_types
