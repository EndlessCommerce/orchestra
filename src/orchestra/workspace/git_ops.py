from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    def __init__(self, command: list[str], returncode: int, stderr: str) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"git command failed ({returncode}): {' '.join(command)}\n{stderr}")


def run_git(*args: str, cwd: Path) -> str:
    cmd = ["git", *args]
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(cmd, result.returncode, result.stderr.strip())
    return result.stdout.strip()


def rev_parse(ref: str, *, cwd: Path) -> str:
    return run_git("rev-parse", ref, cwd=cwd)


def current_branch(*, cwd: Path) -> str:
    return run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)


def create_branch(name: str, *, cwd: Path) -> None:
    run_git("checkout", "-b", name, cwd=cwd)


def checkout(ref: str, *, cwd: Path) -> None:
    run_git("checkout", ref, cwd=cwd)


def add(paths: list[str], *, cwd: Path) -> None:
    if not paths:
        return
    run_git("add", "--", *paths, cwd=cwd)


def commit(
    message: str,
    *,
    author: str,
    trailers: dict[str, str] | None = None,
    cwd: Path,
) -> str:
    args = ["commit", "--author", author, "-m", message]
    for key, value in (trailers or {}).items():
        args.extend(["--trailer", f"{key}: {value}"])
    run_git(*args, cwd=cwd)
    return rev_parse("HEAD", cwd=cwd)


def status(*, cwd: Path) -> str:
    return run_git("status", "--porcelain", cwd=cwd)


def log(n: int, *, fmt: str = "%H %s", cwd: Path) -> str:
    return run_git("log", f"-n{n}", f"--format={fmt}", cwd=cwd)


def diff(*, staged: bool = False, cwd: Path) -> str:
    args = ["diff"]
    if staged:
        args.append("--cached")
    return run_git(*args, cwd=cwd)


def is_git_repo(path: Path) -> bool:
    try:
        run_git("rev-parse", "--is-inside-work-tree", cwd=path)
        return True
    except (GitError, FileNotFoundError):
        return False



def worktree_add(worktree_path: Path, branch: str, *, cwd: Path) -> None:
    run_git("worktree", "add", str(worktree_path), "-b", branch, cwd=cwd)


def worktree_remove(worktree_path: Path, *, cwd: Path) -> None:
    run_git("worktree", "remove", str(worktree_path), "--force", cwd=cwd)


def worktree_list(*, cwd: Path) -> list[str]:
    output = run_git("worktree", "list", "--porcelain", cwd=cwd)
    return output.splitlines() if output else []


def merge(branch: str, *, cwd: Path) -> None:
    run_git("merge", "--no-ff", "--no-commit", branch, cwd=cwd)


def merge_abort(*, cwd: Path) -> None:
    run_git("merge", "--abort", cwd=cwd)


def merge_conflicts(*, cwd: Path) -> list[str]:
    output = run_git("diff", "--name-only", "--diff-filter=U", cwd=cwd)
    return output.splitlines() if output else []


def read_file(path: Path) -> str:
    return path.read_text()


def branch_delete(name: str, *, cwd: Path) -> None:
    run_git("branch", "-D", name, cwd=cwd)
