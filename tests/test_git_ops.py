from pathlib import Path

import pytest

from orchestra.workspace.git_ops import (
    GitError,
    add,
    commit,
    create_branch,
    checkout,
    current_branch,
    diff,
    is_git_repo,
    log,
    rev_parse,
    run_git,
    status,
)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repo with an initial commit."""
    run_git("init", cwd=tmp_path)
    run_git("config", "user.email", "test@test.com", cwd=tmp_path)
    run_git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("# Hello\n")
    run_git("add", "README.md", cwd=tmp_path)
    run_git("commit", "-m", "Initial commit", cwd=tmp_path)
    return tmp_path


class TestRunGit:
    def test_returns_stdout(self, git_repo: Path) -> None:
        output = run_git("rev-parse", "--is-inside-work-tree", cwd=git_repo)
        assert output == "true"

    def test_raises_git_error_on_failure(self, tmp_path: Path) -> None:
        with pytest.raises(GitError) as exc_info:
            run_git("log", cwd=tmp_path)
        assert exc_info.value.returncode != 0
        assert exc_info.value.command[0] == "git"


class TestRevParse:
    def test_resolves_head(self, git_repo: Path) -> None:
        sha = rev_parse("HEAD", cwd=git_repo)
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_bad_ref_raises(self, git_repo: Path) -> None:
        with pytest.raises(GitError):
            rev_parse("nonexistent-ref-abc123", cwd=git_repo)


class TestCurrentBranch:
    def test_returns_branch_name(self, git_repo: Path) -> None:
        branch = current_branch(cwd=git_repo)
        assert branch in ("main", "master")


class TestCreateBranchAndCheckout:
    def test_create_branch(self, git_repo: Path) -> None:
        create_branch("feature/test", cwd=git_repo)
        assert current_branch(cwd=git_repo) == "feature/test"

    def test_checkout_existing_branch(self, git_repo: Path) -> None:
        original = current_branch(cwd=git_repo)
        create_branch("new-branch", cwd=git_repo)
        assert current_branch(cwd=git_repo) == "new-branch"
        checkout(original, cwd=git_repo)
        assert current_branch(cwd=git_repo) == original


class TestAddAndCommit:
    def test_add_and_commit(self, git_repo: Path) -> None:
        (git_repo / "new_file.py").write_text("print('hello')\n")
        add(["new_file.py"], cwd=git_repo)
        sha = commit(
            "Add new file",
            author="Test Agent <test@agent.com>",
            cwd=git_repo,
        )
        assert len(sha) == 40
        log_output = log(1, fmt="%s", cwd=git_repo)
        assert "Add new file" in log_output

    def test_commit_with_trailers(self, git_repo: Path) -> None:
        (git_repo / "a.txt").write_text("content\n")
        add(["a.txt"], cwd=git_repo)
        sha = commit(
            "Add a.txt",
            author="Agent (model) <orchestra@local>",
            trailers={"Orchestra-Model": "test-model", "Orchestra-Turn": "1"},
            cwd=git_repo,
        )
        assert len(sha) == 40
        full_log = log(1, fmt="%B", cwd=git_repo)
        assert "Orchestra-Model: test-model" in full_log
        assert "Orchestra-Turn: 1" in full_log

    def test_commit_author(self, git_repo: Path) -> None:
        (git_repo / "b.txt").write_text("b\n")
        add(["b.txt"], cwd=git_repo)
        commit(
            "Add b.txt",
            author="MyAgent (claude-3.5) <orchestra@local>",
            cwd=git_repo,
        )
        author_output = log(1, fmt="%an <%ae>", cwd=git_repo)
        assert "MyAgent (claude-3.5)" in author_output
        assert "orchestra@local" in author_output

    def test_add_empty_list_is_noop(self, git_repo: Path) -> None:
        add([], cwd=git_repo)


class TestStatus:
    def test_clean_repo(self, git_repo: Path) -> None:
        assert status(cwd=git_repo) == ""

    def test_untracked_file(self, git_repo: Path) -> None:
        (git_repo / "untracked.txt").write_text("x\n")
        output = status(cwd=git_repo)
        assert "untracked.txt" in output


class TestDiff:
    def test_no_changes(self, git_repo: Path) -> None:
        assert diff(cwd=git_repo) == ""

    def test_unstaged_diff(self, git_repo: Path) -> None:
        (git_repo / "README.md").write_text("# Changed\n")
        output = diff(cwd=git_repo)
        assert "+# Changed" in output

    def test_staged_diff(self, git_repo: Path) -> None:
        (git_repo / "README.md").write_text("# Staged\n")
        add(["README.md"], cwd=git_repo)
        output = diff(staged=True, cwd=git_repo)
        assert "+# Staged" in output


class TestIsGitRepo:
    def test_valid_repo(self, git_repo: Path) -> None:
        assert is_git_repo(git_repo) is True

    def test_non_repo(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path) is False

    def test_nonexistent_path(self, tmp_path: Path) -> None:
        assert is_git_repo(tmp_path / "does_not_exist") is False


class TestLog:
    def test_log_single_commit(self, git_repo: Path) -> None:
        output = log(1, fmt="%s", cwd=git_repo)
        assert "Initial commit" in output

    def test_log_multiple_commits(self, git_repo: Path) -> None:
        (git_repo / "f1.txt").write_text("1\n")
        add(["f1.txt"], cwd=git_repo)
        commit("Second commit", author="Test <t@t.com>", cwd=git_repo)
        output = log(2, fmt="%s", cwd=git_repo)
        assert "Second commit" in output
        assert "Initial commit" in output
