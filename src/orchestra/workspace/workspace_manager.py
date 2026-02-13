from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace import git_ops
from orchestra.workspace.repo_context import RepoContext
from orchestra.workspace.session_branch import (
    create_session_branches,
    restore_original_branches,
)
from orchestra.workspace.worktree_manager import WorktreeMergeResult, WorktreeManager

if TYPE_CHECKING:
    from orchestra.config.settings import OrchestraConfig
    from orchestra.events.types import Event
    from orchestra.workspace.commit_message import CommitMessageGenerator

logger = logging.getLogger(__name__)


class EventEmitter:
    """Protocol for event emission (satisfied by EventDispatcher)."""

    def emit(self, event_type: str, **data: Any) -> None: ...


class WorkspaceManager:
    def __init__(
        self,
        config: OrchestraConfig,
        event_emitter: EventEmitter,
        commit_gen: CommitMessageGenerator,
    ) -> None:
        self._config = config
        self._event_emitter = event_emitter
        self._commit_gen = commit_gen
        self._branch_infos: dict = {}
        self._repo_contexts: dict[str, RepoContext] = {}
        self._pipeline_name = ""
        self._session_id = ""
        self._current_node_id = ""
        self._worktree_manager: WorktreeManager | None = None
        self._active_worktrees: dict[str, dict[str, RepoContext]] = {}

    @property
    def has_workspace(self) -> bool:
        return bool(self._config.workspace.repos)

    def setup_session(
        self, pipeline_name: str, session_id: str
    ) -> dict[str, RepoContext]:
        self._pipeline_name = pipeline_name
        self._session_id = session_id

        config_dir = self._config.config_dir or Path.cwd()
        self._branch_infos = create_session_branches(
            self._config.workspace.repos,
            pipeline_name,
            session_id,
            config_dir,
        )

        self._repo_contexts = {}
        for name, info in self._branch_infos.items():
            self._repo_contexts[name] = RepoContext(
                name=name,
                path=info.repo_path,
                branch=info.branch_name,
                base_sha=info.base_sha,
            )
            self._event_emitter.emit(
                "SessionBranchCreated",
                repo_name=name,
                branch_name=info.branch_name,
                base_sha=info.base_sha,
                repo_path=str(info.repo_path),
            )

        return self._repo_contexts

    def teardown_session(self) -> None:
        if self._branch_infos:
            restore_original_branches(self._branch_infos)

    def _ensure_worktree_manager(self) -> WorktreeManager:
        if self._worktree_manager is None:
            first_repo = next(iter(self._repo_contexts.values()), None)
            branch_prefix = "orchestra/"
            if first_repo:
                repo_config = self._config.workspace.repos.get(first_repo.name)
                if repo_config:
                    branch_prefix = repo_config.branch_prefix
            self._worktree_manager = WorktreeManager(
                repo_contexts=self._repo_contexts,
                session_id=self._session_id,
                pipeline_name=self._pipeline_name,
                branch_prefix=branch_prefix,
                event_emitter=self._event_emitter,
            )
        return self._worktree_manager

    def create_worktrees_for_branch(self, branch_id: str) -> dict[str, RepoContext]:
        wt_mgr = self._ensure_worktree_manager()
        wt_contexts = wt_mgr.create_worktrees(branch_id)
        self._active_worktrees[branch_id] = wt_contexts
        return wt_contexts

    def merge_worktrees(self, branch_ids: list[str]) -> WorktreeMergeResult:
        wt_mgr = self._ensure_worktree_manager()
        result = wt_mgr.merge_worktrees(branch_ids)
        if result.success:
            for bid in branch_ids:
                self._active_worktrees.pop(bid, None)
        return result

    def on_event(self, event: Event) -> None:
        from orchestra.events.types import StageCompleted, StageFailed, StageStarted

        if isinstance(event, StageStarted):
            self._current_node_id = event.node_id
        elif isinstance(event, (StageCompleted, StageFailed)):
            self._current_node_id = ""

    def on_turn_callback(self, turn: AgentTurn) -> None:
        node_id = self._current_node_id or "unknown"

        if turn.files_written:
            self._commit_turn(turn, node_id)

        self._emit_agent_turn_completed(turn, node_id)

    def _commit_turn(self, turn: AgentTurn, node_id: str) -> None:
        for repo_name, repo_ctx in self._repo_contexts.items():
            # Determine the working directory: use worktree path if available
            cwd = self._resolve_commit_cwd(repo_name, repo_ctx)
            repo_files = self._match_files_to_repo(turn.files_written, cwd)
            if not repo_files:
                continue

            try:
                git_ops.add(repo_files, cwd=cwd)

                staged_diff = git_ops.diff(staged=True, cwd=cwd)
                if not staged_diff:
                    continue

                intent = self._extract_intent(turn)
                message = self._commit_gen.generate(staged_diff, intent)

                author = f"{node_id} ({turn.model}) <orchestra@local>"
                trailers = {
                    "Orchestra-Model": turn.model,
                    "Orchestra-Provider": turn.provider,
                    "Orchestra-Node": node_id,
                    "Orchestra-Pipeline": self._pipeline_name,
                    "Orchestra-Session": self._session_id,
                    "Orchestra-Turn": str(turn.turn_number),
                }

                sha = git_ops.commit(
                    message,
                    author=author,
                    trailers=trailers,
                    cwd=cwd,
                )

                turn.git_sha = sha
                turn.commit_message = message

                self._event_emitter.emit(
                    "AgentCommitCreated",
                    repo_name=repo_name,
                    node_id=node_id,
                    sha=sha,
                    message=message,
                    files=repo_files,
                    turn_number=turn.turn_number,
                )
            except Exception:
                logger.warning(
                    "Failed to commit turn %d in repo '%s'",
                    turn.turn_number,
                    repo_name,
                    exc_info=True,
                )

    def _resolve_commit_cwd(self, repo_name: str, repo_ctx: RepoContext) -> Path:
        """Return the worktree path if the repo is currently in a worktree, else the repo path."""
        for wt_contexts in self._active_worktrees.values():
            wt_ctx = wt_contexts.get(repo_name)
            if wt_ctx and wt_ctx.worktree_path:
                return wt_ctx.worktree_path
        if repo_ctx.worktree_path:
            return repo_ctx.worktree_path
        return repo_ctx.path

    def _emit_agent_turn_completed(self, turn: AgentTurn, node_id: str) -> None:
        self._event_emitter.emit(
            "AgentTurnCompleted",
            node_id=node_id,
            turn_number=turn.turn_number,
            model=turn.model,
            provider=turn.provider,
            messages=json.dumps(turn.messages) if turn.messages else "",
            tool_calls=json.dumps(turn.tool_calls) if turn.tool_calls else "",
            files_written=turn.files_written,
            token_usage=turn.token_usage,
            agent_state=json.dumps(turn.agent_state) if turn.agent_state else "",
            git_sha=turn.git_sha,
            commit_message=turn.commit_message,
        )

    def _match_files_to_repo(self, files: list[str], repo_path: Path) -> list[str]:
        repo_str = str(repo_path.resolve())
        matched: list[str] = []
        for f in files:
            abs_f = str(Path(f).resolve())
            if abs_f.startswith(repo_str):
                matched.append(abs_f)
        return matched

    def _extract_intent(self, turn: AgentTurn) -> str:
        for msg in reversed(turn.messages):
            if msg.get("role") == "user" or msg.get("role") == "human":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    return content[:200]
        if turn.tool_calls:
            names = [tc.get("name", "") for tc in turn.tool_calls[:3]]
            return f"Tool calls: {', '.join(names)}"
        return "Agent changes"
