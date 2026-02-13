from pathlib import Path

import pytest

from orchestra.config.settings import RepoConfig
from orchestra.workspace.git_ops import current_branch, rev_parse, run_git
from orchestra.workspace.session_branch import (
    SessionBranchInfo,
    WorkspaceError,
    create_session_branches,
    restore_original_branches,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    run_git("init", cwd=tmp_path)
    run_git("config", "user.email", "test@test.com", cwd=tmp_path)
    run_git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=tmp_path)
    run_git("commit", "-m", "Initial commit", cwd=tmp_path)
    return tmp_path


@pytest.fixture()
def two_repos(tmp_path: Path) -> tuple[Path, Path]:
    for name in ("backend", "frontend"):
        repo = tmp_path / name
        repo.mkdir()
        run_git("init", cwd=repo)
        run_git("config", "user.email", "test@test.com", cwd=repo)
        run_git("config", "user.name", "Test", cwd=repo)
        (repo / "README.md").write_text(f"# {name}\n")
        run_git("add", "README.md", cwd=repo)
        run_git("commit", "-m", "Initial commit", cwd=repo)
    return tmp_path / "backend", tmp_path / "frontend"


class TestCreateSessionBranches:
    def test_creates_branch(self, git_repo: Path) -> None:
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "my-pipeline", "abc123", git_repo.parent)
        assert "project" in infos
        assert current_branch(cwd=git_repo) == infos["project"].branch_name

    def test_branch_naming(self, git_repo: Path) -> None:
        repos = {"project": RepoConfig(path=str(git_repo), branch_prefix="orchestra/")}
        infos = create_session_branches(repos, "test-pipe", "sess-id", git_repo.parent)
        assert infos["project"].branch_name == "orchestra/test-pipe/sess-id"

    def test_sanitizes_pipeline_name(self, git_repo: Path) -> None:
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "my pipeline!", "id1", git_repo.parent)
        assert " " not in infos["project"].branch_name
        assert "!" not in infos["project"].branch_name

    def test_records_base_sha(self, git_repo: Path) -> None:
        expected_sha = rev_parse("HEAD", cwd=git_repo)
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "pipe", "id", git_repo.parent)
        assert infos["project"].base_sha == expected_sha

    def test_records_original_branch(self, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "pipe", "id", git_repo.parent)
        assert infos["project"].original_branch == original

    def test_multi_repo(self, two_repos: tuple[Path, Path]) -> None:
        backend, frontend = two_repos
        repos = {
            "backend": RepoConfig(path=str(backend)),
            "frontend": RepoConfig(path=str(frontend)),
        }
        infos = create_session_branches(repos, "pipe", "id", backend.parent)
        assert len(infos) == 2
        assert current_branch(cwd=backend) == infos["backend"].branch_name
        assert current_branch(cwd=frontend) == infos["frontend"].branch_name

    def test_relative_path_resolution(self, git_repo: Path) -> None:
        repos = {"project": RepoConfig(path=".")}
        infos = create_session_branches(repos, "pipe", "id", git_repo)
        assert infos["project"].repo_path == git_repo.resolve()

    def test_nonexistent_path_raises(self, tmp_path: Path) -> None:
        repos = {"project": RepoConfig(path=str(tmp_path / "nope"))}
        with pytest.raises(WorkspaceError, match="does not exist"):
            create_session_branches(repos, "pipe", "id", tmp_path)

    def test_non_git_repo_raises(self, tmp_path: Path) -> None:
        not_git = tmp_path / "not-git"
        not_git.mkdir()
        repos = {"project": RepoConfig(path=str(not_git))}
        with pytest.raises(WorkspaceError, match="Not a git repository"):
            create_session_branches(repos, "pipe", "id", tmp_path)


class TestRestoreOriginalBranches:
    def test_restores_branch(self, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "pipe", "id", git_repo.parent)
        assert current_branch(cwd=git_repo) != original
        restore_original_branches(infos)
        assert current_branch(cwd=git_repo) == original

    def test_session_branch_persists_after_restore(self, git_repo: Path) -> None:
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "pipe", "id", git_repo.parent)
        branch_name = infos["project"].branch_name
        restore_original_branches(infos)
        branches = run_git("branch", "--list", cwd=git_repo)
        assert branch_name in branches

    def test_idempotent_restore(self, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        repos = {"project": RepoConfig(path=str(git_repo))}
        infos = create_session_branches(repos, "pipe", "id", git_repo.parent)
        restore_original_branches(infos)
        restore_original_branches(infos)
        assert current_branch(cwd=git_repo) == original

    def test_logs_warning_on_failure(self, git_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
        info = SessionBranchInfo(
            repo_name="project",
            repo_path=git_repo,
            branch_name="session-branch",
            base_sha="abc",
            original_branch="nonexistent-branch-xyz",
        )
        restore_original_branches({"project": info})
        assert "Failed to restore branch" in caplog.text
