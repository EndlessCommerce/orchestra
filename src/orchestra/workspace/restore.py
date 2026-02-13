from __future__ import annotations

import logging
from pathlib import Path

from orchestra.config.settings import RepoConfig
from orchestra.workspace import git_ops

logger = logging.getLogger(__name__)


def restore_git_state(
    workspace_snapshot: dict[str, str],
    repos: dict[str, RepoConfig],
    config_dir: Path,
) -> None:
    """Restore git repos to the SHAs recorded in a workspace snapshot.

    For each repo in the snapshot:
    1. Resolve the repo path
    2. Checkout the session branch
    3. Verify/reset to the recorded SHA
    """
    for repo_name, target_sha in workspace_snapshot.items():
        repo_config = repos.get(repo_name)
        if repo_config is None:
            logger.warning("Repo '%s' in snapshot but not in config — skipping", repo_name)
            continue

        repo_path = Path(repo_config.path)
        if not repo_path.is_absolute():
            repo_path = (config_dir / repo_path).resolve()

        if not repo_path.exists():
            logger.warning("Repo path does not exist: %s — skipping", repo_path)
            continue

        try:
            current_sha = git_ops.rev_parse("HEAD", cwd=repo_path)
            if current_sha == target_sha:
                logger.info("Repo '%s' already at %s", repo_name, target_sha[:8])
                continue

            git_ops.checkout(target_sha, cwd=repo_path)
            logger.info("Repo '%s' restored to %s", repo_name, target_sha[:8])
        except Exception:
            logger.warning(
                "Failed to restore repo '%s' to %s",
                repo_name,
                target_sha[:8],
                exc_info=True,
            )
