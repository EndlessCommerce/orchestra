from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orchestra.workspace import git_ops
from orchestra.workspace.git_ops import GitError
from orchestra.workspace.repo_context import RepoContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EventEmitter:
    """Protocol for event emission (satisfied by EventDispatcher)."""

    def emit(self, event_type: str, **data: Any) -> None: ...


@dataclass
class WorktreeMergeResult:
    success: bool
    conflicts: dict[str, dict[str, Any]] = field(default_factory=dict)
    merged_shas: dict[str, str] = field(default_factory=dict)


class WorktreeManager:
    def __init__(
        self,
        repo_contexts: dict[str, RepoContext],
        session_id: str,
        pipeline_name: str,
        branch_prefix: str,
        event_emitter: EventEmitter,
    ) -> None:
        self._repo_contexts = repo_contexts
        self._session_id = session_id
        self._pipeline_name = pipeline_name
        self._branch_prefix = branch_prefix
        self._event_emitter = event_emitter

    def _worktree_base_dir(self, repo_ctx: RepoContext) -> Path:
        return repo_ctx.path / ".orchestra" / "worktrees" / self._session_id

    def _worktree_branch_name(self, branch_id: str) -> str:
        return f"{self._branch_prefix}{self._pipeline_name}/{self._session_id}/{branch_id}"

    def create_worktrees(self, branch_id: str) -> dict[str, RepoContext]:
        result: dict[str, RepoContext] = {}
        for repo_name, repo_ctx in self._repo_contexts.items():
            base_dir = self._worktree_base_dir(repo_ctx)
            wt_path = base_dir / branch_id
            wt_branch = self._worktree_branch_name(branch_id)

            git_ops.worktree_add(wt_path, wt_branch, cwd=repo_ctx.path)

            wt_ctx = RepoContext(
                name=repo_ctx.name,
                path=repo_ctx.path,
                branch=wt_branch,
                base_sha=repo_ctx.base_sha,
                worktree_path=wt_path,
            )
            result[repo_name] = wt_ctx

            self._event_emitter.emit(
                "WorktreeCreated",
                repo_name=repo_name,
                branch_id=branch_id,
                worktree_path=str(wt_path),
                worktree_branch=wt_branch,
            )

        return result

    def merge_worktrees(self, branch_ids: list[str]) -> WorktreeMergeResult:
        all_conflicts: dict[str, dict[str, Any]] = {}
        merged_shas: dict[str, str] = {}

        for repo_name, repo_ctx in self._repo_contexts.items():
            repo_conflicts = self._merge_repo_worktrees(repo_ctx, branch_ids)
            if repo_conflicts is not None:
                all_conflicts[repo_name] = repo_conflicts
            else:
                merged_shas[repo_name] = git_ops.rev_parse("HEAD", cwd=repo_ctx.path)

        success = len(all_conflicts) == 0

        if success:
            self._cleanup_worktrees(branch_ids)
            self._event_emitter.emit(
                "WorktreeMerged",
                repo_name="all",
                branch_ids=branch_ids,
                merged_sha=next(iter(merged_shas.values()), ""),
            )
        else:
            self._event_emitter.emit(
                "WorktreeMergeConflict",
                repo_name="all",
                branch_ids=branch_ids,
                conflicting_files=[
                    f
                    for c in all_conflicts.values()
                    for f in c.get("conflicting_files", [])
                ],
            )

        return WorktreeMergeResult(
            success=success,
            conflicts=all_conflicts,
            merged_shas=merged_shas,
        )

    def _merge_repo_worktrees(
        self,
        repo_ctx: RepoContext,
        branch_ids: list[str],
    ) -> dict[str, Any] | None:
        git_ops.checkout(repo_ctx.branch, cwd=repo_ctx.path)

        for branch_id in branch_ids:
            wt_branch = self._worktree_branch_name(branch_id)
            try:
                git_ops.merge(wt_branch, cwd=repo_ctx.path)
                # Complete the merge
                git_ops.commit(
                    f"Merge {branch_id} into session branch",
                    author="Orchestra <orchestra@local>",
                    cwd=repo_ctx.path,
                )
            except GitError:
                conflicting = git_ops.merge_conflicts(cwd=repo_ctx.path)
                conflict_markers: dict[str, str] = {}
                for f in conflicting:
                    fpath = repo_ctx.path / f
                    if fpath.exists():
                        conflict_markers[f] = git_ops.read_file(fpath)

                git_ops.merge_abort(cwd=repo_ctx.path)

                return {
                    "conflicting_files": conflicting,
                    "conflicts": conflict_markers,
                    "failed_branch_id": branch_id,
                }

        return None

    def _cleanup_worktrees(self, branch_ids: list[str]) -> None:
        for repo_name, repo_ctx in self._repo_contexts.items():
            for branch_id in branch_ids:
                wt_path = self._worktree_base_dir(repo_ctx) / branch_id
                wt_branch = self._worktree_branch_name(branch_id)
                try:
                    if wt_path.exists():
                        git_ops.worktree_remove(wt_path, cwd=repo_ctx.path)
                    git_ops.branch_delete(wt_branch, cwd=repo_ctx.path)
                except GitError:
                    logger.warning(
                        "Failed to clean up worktree %s in repo %s",
                        branch_id,
                        repo_name,
                        exc_info=True,
                    )

    def cleanup_worktrees(self, branch_ids: list[str]) -> None:
        self._cleanup_worktrees(branch_ids)
