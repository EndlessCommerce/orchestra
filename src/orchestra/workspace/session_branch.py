from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from orchestra.config.settings import RepoConfig
from orchestra.workspace import git_ops

logger = logging.getLogger(__name__)


class WorkspaceError(Exception):
    pass


@dataclass
class SessionBranchInfo:
    repo_name: str
    repo_path: Path
    branch_name: str
    base_sha: str
    original_branch: str


@dataclass
class PrepareResult:
    repo_name: str
    repo_path: Path
    action: str  # "cloned", "fetched", "none"


def _sanitize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_/.-]", "-", name)


def prepare_repos(
    repos: dict[str, RepoConfig],
    config_dir: Path,
) -> list[PrepareResult]:
    results: list[PrepareResult] = []

    for repo_name, repo_config in repos.items():
        repo_path = Path(repo_config.path)
        if not repo_path.is_absolute():
            repo_path = (config_dir / repo_path).resolve()

        has_remote = bool(repo_config.remote)
        path_exists = repo_path.exists()

        if not path_exists and not has_remote:
            raise WorkspaceError(
                f"Repo '{repo_name}' path does not exist ({repo_path}) "
                f"and no remote is configured. Either create the directory "
                f"or set 'remote' in workspace.repos.{repo_name}."
            )

        depth = repo_config.clone_depth if repo_config.clone_depth > 0 else None

        if not path_exists and has_remote:
            git_ops.clone(repo_config.remote, repo_path, depth=depth)
            results.append(PrepareResult(repo_name, repo_path, "cloned"))
        elif path_exists and has_remote:
            git_ops.fetch("origin", cwd=repo_path, depth=depth)
            results.append(PrepareResult(repo_name, repo_path, "fetched"))
        else:
            results.append(PrepareResult(repo_name, repo_path, "none"))

    return results


def create_session_branches(
    repos: dict[str, RepoConfig],
    pipeline_name: str,
    session_id: str,
    config_dir: Path,
) -> dict[str, SessionBranchInfo]:
    safe_pipeline = _sanitize_name(pipeline_name)
    branch_infos: dict[str, SessionBranchInfo] = {}

    for repo_name, repo_config in repos.items():
        repo_path = Path(repo_config.path)
        if not repo_path.is_absolute():
            repo_path = (config_dir / repo_path).resolve()

        if not repo_path.exists():
            raise WorkspaceError(f"Repo path does not exist: {repo_path}")
        if not git_ops.is_git_repo(repo_path):
            raise WorkspaceError(f"Not a git repository: {repo_path}")

        original_branch = git_ops.current_branch(cwd=repo_path)
        base_sha = git_ops.rev_parse("HEAD", cwd=repo_path)
        branch_name = f"{repo_config.branch_prefix}{safe_pipeline}/{session_id}"

        git_ops.create_branch(branch_name, cwd=repo_path)

        branch_infos[repo_name] = SessionBranchInfo(
            repo_name=repo_name,
            repo_path=repo_path,
            branch_name=branch_name,
            base_sha=base_sha,
            original_branch=original_branch,
        )

    return branch_infos


def restore_original_branches(branch_infos: dict[str, SessionBranchInfo]) -> None:
    for info in branch_infos.values():
        try:
            git_ops.checkout(info.original_branch, cwd=info.repo_path)
        except Exception:
            logger.warning(
                "Failed to restore branch '%s' in repo '%s' at %s",
                info.original_branch,
                info.repo_name,
                info.repo_path,
            )
