"""Tests for git worktree operations added in Stage 6b."""

from pathlib import Path

import pytest

from orchestra.workspace.git_ops import (
    GitError,
    add,
    branch_delete,
    checkout,
    commit,
    create_branch,
    current_branch,
    merge,
    merge_abort,
    merge_conflicts,
    read_file,
    rev_parse,
    run_git,
    worktree_add,
    worktree_list,
    worktree_remove,
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


class TestWorktreeAdd:
    def test_creates_worktree_directory(self, git_repo: Path, tmp_path: Path) -> None:
        wt_path = tmp_path / "worktrees" / "agent-a"
        worktree_add(wt_path, "wt-branch-a", cwd=git_repo)
        assert wt_path.exists()
        assert wt_path.is_dir()
        assert (wt_path / "README.md").exists()

    def test_creates_new_branch(self, git_repo: Path, tmp_path: Path) -> None:
        wt_path = tmp_path / "worktrees" / "agent-b"
        worktree_add(wt_path, "wt-branch-b", cwd=git_repo)
        branch = current_branch(cwd=wt_path)
        assert branch == "wt-branch-b"

    def test_worktree_has_same_content(self, git_repo: Path, tmp_path: Path) -> None:
        wt_path = tmp_path / "worktrees" / "agent-c"
        worktree_add(wt_path, "wt-branch-c", cwd=git_repo)
        assert (wt_path / "README.md").read_text() == "# Hello\n"

    def test_worktree_starts_at_current_head(self, git_repo: Path, tmp_path: Path) -> None:
        main_sha = rev_parse("HEAD", cwd=git_repo)
        wt_path = tmp_path / "worktrees" / "agent-d"
        worktree_add(wt_path, "wt-branch-d", cwd=git_repo)
        wt_sha = rev_parse("HEAD", cwd=wt_path)
        assert wt_sha == main_sha


class TestWorktreeRemove:
    def test_removes_worktree_directory(self, git_repo: Path, tmp_path: Path) -> None:
        wt_path = tmp_path / "worktrees" / "agent-rm"
        worktree_add(wt_path, "wt-branch-rm", cwd=git_repo)
        assert wt_path.exists()
        worktree_remove(wt_path, cwd=git_repo)
        assert not wt_path.exists()

    def test_remove_nonexistent_raises(self, git_repo: Path, tmp_path: Path) -> None:
        with pytest.raises(GitError):
            worktree_remove(tmp_path / "no-such-worktree", cwd=git_repo)


class TestWorktreeList:
    def test_lists_main_worktree(self, git_repo: Path) -> None:
        lines = worktree_list(cwd=git_repo)
        assert any("worktree" in line for line in lines)

    def test_lists_added_worktree(self, git_repo: Path, tmp_path: Path) -> None:
        wt_path = tmp_path / "worktrees" / "agent-list"
        worktree_add(wt_path, "wt-branch-list", cwd=git_repo)
        lines = worktree_list(cwd=git_repo)
        assert any(str(wt_path) in line for line in lines)


class TestWorktreeIsolation:
    def test_write_in_worktree_a_not_visible_in_b(self, git_repo: Path, tmp_path: Path) -> None:
        wt_a = tmp_path / "worktrees" / "agent-a"
        wt_b = tmp_path / "worktrees" / "agent-b"
        worktree_add(wt_a, "wt-branch-a", cwd=git_repo)
        worktree_add(wt_b, "wt-branch-b", cwd=git_repo)

        # Write a file in worktree A
        (wt_a / "agent_a_file.txt").write_text("from agent A\n")
        add(["agent_a_file.txt"], cwd=wt_a)
        commit("Agent A commit", author="AgentA <a@test.com>", cwd=wt_a)

        # File should not exist in worktree B
        assert not (wt_b / "agent_a_file.txt").exists()

    def test_write_in_worktree_not_visible_in_main(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "worktrees" / "agent-x"
        worktree_add(wt, "wt-branch-x", cwd=git_repo)

        (wt / "agent_x_file.txt").write_text("from agent X\n")
        add(["agent_x_file.txt"], cwd=wt)
        commit("Agent X commit", author="AgentX <x@test.com>", cwd=wt)

        assert not (git_repo / "agent_x_file.txt").exists()


class TestMerge:
    def test_clean_merge(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "worktrees" / "agent-merge"
        worktree_add(wt, "wt-branch-merge", cwd=git_repo)

        # Make a change in the worktree
        (wt / "new_file.txt").write_text("new content\n")
        add(["new_file.txt"], cwd=wt)
        commit("Add new file", author="Agent <a@test.com>", cwd=wt)

        # Merge back into main
        main_branch = current_branch(cwd=git_repo)
        assert main_branch in ("main", "master")
        merge("wt-branch-merge", cwd=git_repo)
        # Complete the merge commit
        commit("Merge worktree", author="Orchestra <o@test.com>", cwd=git_repo)

        # Verify the file is now in main
        assert (git_repo / "new_file.txt").exists()
        assert (git_repo / "new_file.txt").read_text() == "new content\n"

    def test_merge_conflict_detected(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "worktrees" / "agent-conflict"
        worktree_add(wt, "wt-branch-conflict", cwd=git_repo)

        # Edit the same file in both places
        (wt / "README.md").write_text("# Worktree version\n")
        add(["README.md"], cwd=wt)
        commit("Worktree edit", author="Agent <a@test.com>", cwd=wt)

        (git_repo / "README.md").write_text("# Main version\n")
        add(["README.md"], cwd=git_repo)
        commit("Main edit", author="Test <t@test.com>", cwd=git_repo)

        # Merge should fail with conflict
        with pytest.raises(GitError):
            merge("wt-branch-conflict", cwd=git_repo)

    def test_merge_conflicts_lists_files(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "worktrees" / "agent-cf"
        worktree_add(wt, "wt-branch-cf", cwd=git_repo)

        (wt / "README.md").write_text("# Worktree version\n")
        add(["README.md"], cwd=wt)
        commit("Worktree edit", author="Agent <a@test.com>", cwd=wt)

        (git_repo / "README.md").write_text("# Main version\n")
        add(["README.md"], cwd=git_repo)
        commit("Main edit", author="Test <t@test.com>", cwd=git_repo)

        with pytest.raises(GitError):
            merge("wt-branch-cf", cwd=git_repo)

        conflicts = merge_conflicts(cwd=git_repo)
        assert "README.md" in conflicts


class TestMergeAbort:
    def test_aborts_conflicting_merge(self, git_repo: Path, tmp_path: Path) -> None:
        wt = tmp_path / "worktrees" / "agent-abort"
        worktree_add(wt, "wt-branch-abort", cwd=git_repo)

        (wt / "README.md").write_text("# Worktree version\n")
        add(["README.md"], cwd=wt)
        commit("Worktree edit", author="Agent <a@test.com>", cwd=wt)

        (git_repo / "README.md").write_text("# Main version\n")
        add(["README.md"], cwd=git_repo)
        commit("Main edit", author="Test <t@test.com>", cwd=git_repo)

        with pytest.raises(GitError):
            merge("wt-branch-abort", cwd=git_repo)

        # Abort should succeed
        merge_abort(cwd=git_repo)

        # Repo should be back to clean state
        assert (git_repo / "README.md").read_text() == "# Main version\n"


class TestReadFile:
    def test_reads_file_content(self, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        path.write_text("hello world\n")
        assert read_file(path) == "hello world\n"


class TestBranchDelete:
    def test_deletes_branch(self, git_repo: Path) -> None:
        # Create a branch, switch away from it, then delete it
        create_branch("to-delete", cwd=git_repo)
        checkout("main", cwd=git_repo)
        branch_delete("to-delete", cwd=git_repo)
        # Verify branch is gone
        with pytest.raises(GitError):
            rev_parse("to-delete", cwd=git_repo)

    def test_delete_nonexistent_raises(self, git_repo: Path) -> None:
        with pytest.raises(GitError):
            branch_delete("no-such-branch", cwd=git_repo)
