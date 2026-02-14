from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestra.config.settings import RepoConfig
from orchestra.workspace.git_ops import clone, rev_parse, run_git
from orchestra.workspace.session_branch import (
    PrepareResult,
    WorkspaceError,
    prepare_repos,
)


@pytest.fixture()
def source_repo(tmp_path: Path) -> Path:
    """Create a source repo with initial commit."""
    repo = tmp_path / "source"
    repo.mkdir()
    run_git("init", cwd=repo)
    run_git("config", "user.email", "test@test.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=repo)
    run_git("commit", "-m", "Initial commit", cwd=repo)
    return repo


@pytest.fixture()
def bare_remote(tmp_path: Path, source_repo: Path) -> Path:
    """Create a bare remote from the source repo."""
    bare = tmp_path / "remote.git"
    run_git("clone", "--bare", str(source_repo), str(bare), cwd=tmp_path)
    return bare


@pytest.fixture()
def local_clone(tmp_path: Path, bare_remote: Path) -> Path:
    """Create a local clone from the bare remote."""
    target = tmp_path / "local"
    clone(str(bare_remote), target)
    run_git("config", "user.email", "test@test.com", cwd=target)
    run_git("config", "user.name", "Test", cwd=target)
    return target


class TestPrepareReposClone:
    def test_clone_on_start(self, bare_remote: Path, tmp_path: Path) -> None:
        """remote configured + path does not exist → cloned."""
        target = tmp_path / "workspace" / "project"
        repos = {
            "project": RepoConfig(
                path=str(target),
                remote=str(bare_remote),
            )
        }
        results = prepare_repos(repos, tmp_path)
        assert len(results) == 1
        assert results[0].action == "cloned"
        assert results[0].repo_name == "project"
        assert target.exists()
        assert (target / "README.md").exists()

    def test_shallow_clone(self, tmp_path: Path) -> None:
        """clone_depth: 1 → git clone --depth 1 used."""
        # Create a source repo with 2 commits
        source = tmp_path / "src"
        source.mkdir()
        run_git("init", cwd=source)
        run_git("config", "user.email", "test@test.com", cwd=source)
        run_git("config", "user.name", "Test", cwd=source)
        (source / "f1.txt").write_text("1\n")
        run_git("add", "f1.txt", cwd=source)
        run_git("commit", "-m", "First", cwd=source)
        (source / "f2.txt").write_text("2\n")
        run_git("add", "f2.txt", cwd=source)
        run_git("commit", "-m", "Second", cwd=source)

        bare = tmp_path / "shallow-remote.git"
        run_git("clone", "--bare", str(source), str(bare), cwd=tmp_path)

        target = tmp_path / "shallow"
        # Use file:// protocol — local paths ignore --depth
        remote_url = f"file://{bare}"
        repos = {
            "project": RepoConfig(
                path=str(target),
                remote=remote_url,
                clone_depth=1,
            )
        }
        results = prepare_repos(repos, tmp_path)
        assert results[0].action == "cloned"
        # Verify shallow
        output = run_git("rev-list", "--count", "HEAD", cwd=target)
        assert int(output) == 1

    def test_shallow_clone_default(self, bare_remote: Path, tmp_path: Path) -> None:
        """No clone_depth → full clone."""
        target = tmp_path / "full"
        repos = {
            "project": RepoConfig(
                path=str(target),
                remote=str(bare_remote),
            )
        }
        results = prepare_repos(repos, tmp_path)
        assert results[0].action == "cloned"
        # Full clone has all history
        output = run_git("rev-list", "--count", "HEAD", cwd=target)
        assert int(output) >= 1


class TestPrepareReposFetch:
    def test_fetch_on_start(self, local_clone: Path, bare_remote: Path, tmp_path: Path) -> None:
        """remote configured + path exists → fetched."""
        repos = {
            "project": RepoConfig(
                path=str(local_clone),
                remote=str(bare_remote),
            )
        }
        results = prepare_repos(repos, tmp_path)
        assert len(results) == 1
        assert results[0].action == "fetched"

    def test_shallow_fetch(self, local_clone: Path, bare_remote: Path, tmp_path: Path) -> None:
        """fetch with clone_depth uses --depth N."""
        repos = {
            "project": RepoConfig(
                path=str(local_clone),
                remote=str(bare_remote),
                clone_depth=1,
            )
        }
        results = prepare_repos(repos, tmp_path)
        assert results[0].action == "fetched"


class TestPrepareReposNoRemote:
    def test_no_clone_without_remote(self, local_clone: Path, tmp_path: Path) -> None:
        """No remote configured + path exists → no clone/fetch."""
        repos = {
            "project": RepoConfig(path=str(local_clone))
        }
        results = prepare_repos(repos, tmp_path)
        assert len(results) == 1
        assert results[0].action == "none"

    def test_missing_path_no_remote_error(self, tmp_path: Path) -> None:
        """No remote configured + path does not exist → clear error."""
        missing = tmp_path / "does-not-exist"
        repos = {
            "project": RepoConfig(path=str(missing))
        }
        with pytest.raises(WorkspaceError) as exc_info:
            prepare_repos(repos, tmp_path)
        assert "does not exist" in str(exc_info.value)
        assert "no remote" in str(exc_info.value).lower()


class TestPrepareReposEventEmission:
    def test_clone_emits_event(self, bare_remote: Path, tmp_path: Path) -> None:
        """WorkspaceManager.setup_session emits RepoCloned on clone."""
        from orchestra.config.settings import OrchestraConfig, WorkspaceConfig
        from orchestra.workspace.workspace_manager import WorkspaceManager

        target = tmp_path / "workspace" / "project"
        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={"project": RepoConfig(path=str(target), remote=str(bare_remote))}
            ),
            config_dir=tmp_path,
        )
        emitter = MagicMock()
        commit_gen = MagicMock()
        mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
        mgr.setup_session("test-pipe", "abc123")

        # Should have RepoCloned and SessionBranchCreated
        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "RepoCloned" in event_types
        assert "SessionBranchCreated" in event_types

    def test_fetch_emits_event(self, local_clone: Path, bare_remote: Path, tmp_path: Path) -> None:
        """WorkspaceManager.setup_session emits RepoFetched on fetch."""
        from orchestra.config.settings import OrchestraConfig, WorkspaceConfig
        from orchestra.workspace.workspace_manager import WorkspaceManager

        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={"project": RepoConfig(path=str(local_clone), remote=str(bare_remote))}
            ),
            config_dir=tmp_path,
        )
        emitter = MagicMock()
        commit_gen = MagicMock()
        mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
        mgr.setup_session("test-pipe", "abc123")

        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "RepoFetched" in event_types

    def test_no_remote_no_event(self, local_clone: Path, tmp_path: Path) -> None:
        """No remote → no clone/fetch events."""
        from orchestra.config.settings import OrchestraConfig, WorkspaceConfig
        from orchestra.workspace.workspace_manager import WorkspaceManager

        config = OrchestraConfig(
            workspace=WorkspaceConfig(
                repos={"project": RepoConfig(path=str(local_clone))}
            ),
            config_dir=tmp_path,
        )
        emitter = MagicMock()
        commit_gen = MagicMock()
        mgr = WorkspaceManager(config=config, event_emitter=emitter, commit_gen=commit_gen)
        mgr.setup_session("test-pipe", "abc123")

        event_types = [call.args[0] for call in emitter.emit.call_args_list]
        assert "RepoCloned" not in event_types
        assert "RepoFetched" not in event_types
        # Should still have SessionBranchCreated
        assert "SessionBranchCreated" in event_types
