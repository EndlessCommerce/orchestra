from pathlib import Path

import pytest

from orchestra.workspace.git_ops import (
    GitError,
    branch_date,
    branch_delete,
    clone,
    create_branch,
    current_branch,
    fetch,
    list_branches,
    push,
    rev_parse,
    run_git,
)


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
def bare_remote(tmp_path: Path, git_repo: Path) -> Path:
    """Create a bare remote repo cloned from git_repo."""
    bare = tmp_path / "remote.git"
    run_git("clone", "--bare", str(git_repo), str(bare), cwd=tmp_path)
    return bare


class TestClone:
    def test_clone_from_bare_remote(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "cloned"
        clone(str(bare_remote), target)
        assert target.exists()
        assert (target / "README.md").exists()
        sha = rev_parse("HEAD", cwd=target)
        assert len(sha) == 40

    def test_clone_shallow(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "shallow"
        clone(str(bare_remote), target, depth=1)
        assert target.exists()
        assert (target / "README.md").exists()
        # Shallow clone should have limited history
        output = run_git("rev-list", "--count", "HEAD", cwd=target)
        assert int(output) == 1

    def test_clone_full_depth(self, git_repo: Path, bare_remote: Path, tmp_path: Path) -> None:
        # Add a second commit to the source so bare remote has 2 commits
        (git_repo / "file2.txt").write_text("hello\n")
        run_git("add", "file2.txt", cwd=git_repo)
        run_git("commit", "-m", "Second commit", cwd=git_repo)
        run_git("push", str(bare_remote), "HEAD", cwd=git_repo)

        target = tmp_path / "full"
        clone(str(bare_remote), target)
        output = run_git("rev-list", "--count", "HEAD", cwd=target)
        assert int(output) == 2

    def test_clone_bad_url_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "bad"
        with pytest.raises(GitError):
            clone("/nonexistent/repo.git", target)

    def test_clone_existing_path_raises(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "existing"
        target.mkdir()
        (target / "blocker").write_text("x")
        with pytest.raises(GitError):
            clone(str(bare_remote), target)


class TestFetch:
    def test_fetch_from_remote(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "cloned"
        clone(str(bare_remote), target)
        fetch("origin", cwd=target)

    def test_fetch_with_depth(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "cloned"
        clone(str(bare_remote), target)
        fetch("origin", cwd=target, depth=1)

    def test_fetch_bad_remote_raises(self, git_repo: Path) -> None:
        with pytest.raises(GitError):
            fetch("nonexistent-remote", cwd=git_repo)


class TestPush:
    def test_push_to_remote(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "cloned"
        clone(str(bare_remote), target)
        run_git("config", "user.email", "test@test.com", cwd=target)
        run_git("config", "user.name", "Test", cwd=target)

        create_branch("feature/test", cwd=target)
        (target / "new.txt").write_text("new\n")
        run_git("add", "new.txt", cwd=target)
        run_git("commit", "-m", "feature commit", cwd=target)

        push("origin", "feature/test", cwd=target)

        # Verify the remote has the branch
        remote_branches = run_git("branch", cwd=bare_remote)
        assert "feature/test" in remote_branches

    def test_push_with_upstream(self, bare_remote: Path, tmp_path: Path) -> None:
        target = tmp_path / "cloned"
        clone(str(bare_remote), target)
        run_git("config", "user.email", "test@test.com", cwd=target)
        run_git("config", "user.name", "Test", cwd=target)

        create_branch("feature/upstream", cwd=target)
        (target / "up.txt").write_text("up\n")
        run_git("add", "up.txt", cwd=target)
        run_git("commit", "-m", "upstream commit", cwd=target)

        push("origin", "feature/upstream", cwd=target, set_upstream=True)

        # Verify tracking is set up
        tracking = run_git("config", f"branch.feature/upstream.remote", cwd=target)
        assert tracking == "origin"

    def test_push_bad_remote_raises(self, git_repo: Path) -> None:
        with pytest.raises(GitError):
            push("nonexistent-remote", "main", cwd=git_repo)


class TestListBranches:
    def test_list_all_branches(self, git_repo: Path) -> None:
        branches = list_branches("*", cwd=git_repo)
        assert len(branches) >= 1
        default_branch = current_branch(cwd=git_repo)
        assert default_branch in branches

    def test_list_matching_pattern(self, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        create_branch("orchestra/pipeline/abc123", cwd=git_repo)
        run_git("checkout", original, cwd=git_repo)
        branches = list_branches("orchestra/*", cwd=git_repo)
        assert "orchestra/pipeline/abc123" in branches

    def test_list_no_matches(self, git_repo: Path) -> None:
        branches = list_branches("nonexistent-prefix/*", cwd=git_repo)
        assert branches == []


class TestBranchDate:
    def test_branch_date_returns_date(self, git_repo: Path) -> None:
        default_branch = current_branch(cwd=git_repo)
        date = branch_date(default_branch, cwd=git_repo)
        # Date format: 2024-01-15 10:30:45 -0500
        assert len(date) > 10
        assert "-" in date

    def test_branch_date_bad_branch_raises(self, git_repo: Path) -> None:
        with pytest.raises(GitError):
            branch_date("nonexistent-branch-xyz", cwd=git_repo)
