from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

import typer

from orchestra.events.types import (
    AgentCommitCreated,
    AgentTurnCompleted,
    CheckpointSaved,
    Event,
    ParallelCompleted,
    ParallelStarted,
    PipelineCompleted,
    PipelineFailed,
    PipelinePaused,
    PipelineStarted,
    SessionBranchCreated,
    StageCompleted,
    StageFailed,
    StageRetrying,
    StageStarted,
    WorktreeCreated,
    WorktreeMergeConflict,
    WorktreeMerged,
    WorkspaceSnapshotRecorded,
)

from orchestra.storage.type_bundle import to_tagged_data

if TYPE_CHECKING:
    from orchestra.storage.cxdb_client import CxdbClient


def _truncate(s: str, max_len: int = 80) -> str:
    return s if len(s) <= max_len else s[:max_len] + "..."


class EventObserver(Protocol):
    def on_event(self, event: Event) -> None: ...


class StdoutObserver:
    def on_event(self, event: Event) -> None:
        if isinstance(event, PipelineStarted):
            typer.echo(f"[Pipeline] Started: {event.pipeline_name} (goal: {event.goal})")
        elif isinstance(event, PipelineCompleted):
            typer.echo(f"[Pipeline] Completed: {event.pipeline_name} ({event.duration_ms}ms)")
        elif isinstance(event, PipelineFailed):
            typer.echo(f"[Pipeline] FAILED: {event.pipeline_name} — {event.error}")
        elif isinstance(event, PipelinePaused):
            typer.echo(f"[Pipeline] Paused: {event.pipeline_name} at {event.checkpoint_node_id}")
        elif isinstance(event, StageStarted):
            typer.echo(f"  [Stage] Started: {event.node_id} ({event.handler_type})")
        elif isinstance(event, StageCompleted):
            typer.echo(f"  [Stage] Completed: {event.node_id} — {event.status} ({event.duration_ms}ms)")
            if event.response:
                typer.echo(f"    Response: {event.response}")
        elif isinstance(event, StageFailed):
            typer.echo(f"  [Stage] FAILED: {event.node_id} — {event.error}")
        elif isinstance(event, StageRetrying):
            typer.echo(f"  [Stage] Retrying: {event.node_id} (attempt {event.attempt}/{event.max_attempts}, delay {event.delay_ms}ms)")
        elif isinstance(event, AgentTurnCompleted):
            tokens = event.token_usage
            token_str = ""
            if tokens:
                inp = tokens.get("input", 0)
                out = tokens.get("output", 0)
                token_str = f" — {inp + out} tokens"
            typer.echo(f"  [AgentTurn] {event.node_id} turn {event.turn_number} ({event.model}){token_str}")
            if event.tool_calls:
                try:
                    calls = json.loads(event.tool_calls) if isinstance(event.tool_calls, str) else event.tool_calls
                except (json.JSONDecodeError, TypeError):
                    calls = []
                for tc in calls:
                    name = tc.get("name", "?")
                    args = tc.get("args", {})
                    args_summary = ", ".join(f"{k}={_truncate(str(v))}" for k, v in args.items())
                    typer.echo(f"    tool: {name}({args_summary})")
            if event.files_written:
                for f in event.files_written:
                    typer.echo(f"    wrote: {f}")
        elif isinstance(event, CheckpointSaved):
            typer.echo(f"  [Checkpoint] Saved at: {event.node_id}")
        elif isinstance(event, SessionBranchCreated):
            typer.echo(f"  [Workspace] Branch created: {event.branch_name} in {event.repo_name}")
        elif isinstance(event, AgentCommitCreated):
            summary = event.message.split("\n")[0][:60]
            typer.echo(f"  [Commit] {event.sha[:8]} {summary} ({len(event.files)} files)")
        elif isinstance(event, WorktreeCreated):
            typer.echo(f"  [Worktree] Created: {event.branch_id} in {event.repo_name} ({event.worktree_branch})")
        elif isinstance(event, WorktreeMerged):
            typer.echo(f"  [Worktree] Merged: {', '.join(event.branch_ids)} → {event.merged_sha[:8]}")
        elif isinstance(event, WorktreeMergeConflict):
            typer.echo(f"  [Worktree] CONFLICT: {', '.join(event.branch_ids)} — {len(event.conflicting_files)} files")
        elif isinstance(event, WorkspaceSnapshotRecorded):
            repos = ", ".join(f"{k}={v[:8]}" for k, v in event.workspace_snapshot.items())
            typer.echo(f"  [Snapshot] {event.node_id}: {repos}")


class CxdbObserver:
    def __init__(self, client: CxdbClient, context_id: str) -> None:
        self._client = client
        self._context_id = context_id

    def on_event(self, event: Event) -> None:
        if isinstance(event, (PipelineStarted, PipelineCompleted, PipelineFailed, PipelinePaused)):
            self._append_pipeline_lifecycle(event)
        elif isinstance(event, (StageStarted, StageCompleted, StageFailed, StageRetrying)):
            self._append_node_execution(event)
        elif isinstance(event, CheckpointSaved):
            self._append_checkpoint(event)
        elif isinstance(event, AgentTurnCompleted):
            self._append_agent_turn(event)
        elif isinstance(event, (ParallelStarted, ParallelCompleted)):
            self._append_parallel_execution(event)
        elif isinstance(event, (WorktreeCreated, WorktreeMerged)):
            self._append_worktree_event(event)

    def _append_pipeline_lifecycle(self, event: Event) -> None:
        data: dict = {}
        type_version = 1
        if isinstance(event, PipelineStarted):
            data = {
                "pipeline_name": event.pipeline_name,
                "goal": event.goal,
                "status": "started",
                "session_display_id": event.session_display_id,
                "dot_file_path": event.dot_file_path,
                "graph_hash": event.graph_hash,
            }
            type_version = 2  # v2 has dot_file_path + graph_hash
        elif isinstance(event, PipelineCompleted):
            data = {
                "pipeline_name": event.pipeline_name,
                "status": "completed",
                "duration_ms": event.duration_ms,
            }
        elif isinstance(event, PipelineFailed):
            data = {
                "pipeline_name": event.pipeline_name,
                "status": "failed",
                "error": event.error,
            }
        elif isinstance(event, PipelinePaused):
            data = {
                "pipeline_name": event.pipeline_name,
                "status": "paused",
                "session_display_id": event.session_display_id,
            }

        type_id = "dev.orchestra.PipelineLifecycle"
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=type_version,
            data=to_tagged_data(type_id, type_version, data),
        )

    def _append_node_execution(self, event: Event) -> None:
        data: dict = {}
        if isinstance(event, StageStarted):
            data = {
                "node_id": event.node_id,
                "handler_type": event.handler_type,
                "status": "started",
            }
        elif isinstance(event, StageCompleted):
            data = {
                "node_id": event.node_id,
                "handler_type": event.handler_type,
                "status": event.status,
                "prompt": event.prompt,
                "response": event.response,
                "outcome": event.outcome,
                "duration_ms": event.duration_ms,
            }
        elif isinstance(event, StageFailed):
            data = {
                "node_id": event.node_id,
                "handler_type": event.handler_type,
                "status": "failed",
            }
        elif isinstance(event, StageRetrying):
            data = {
                "node_id": event.node_id,
                "status": "retrying",
                "attempt": event.attempt,
                "max_attempts": event.max_attempts,
                "delay_ms": event.delay_ms,
            }

        type_id = "dev.orchestra.NodeExecution"
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=1,
            data=to_tagged_data(type_id, 1, data),
        )

    def _append_agent_turn(self, event: AgentTurnCompleted) -> None:
        type_id = "dev.orchestra.AgentTurn"
        type_version = 2
        data = {
            "turn_number": event.turn_number,
            "node_id": event.node_id,
            "model": event.model,
            "provider": event.provider,
            "messages": event.messages,
            "tool_calls": event.tool_calls,
            "files_written": event.files_written,
            "token_usage": event.token_usage,
            "agent_state": event.agent_state,
            "git_sha": event.git_sha,
            "commit_message": event.commit_message,
        }
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=type_version,
            data=to_tagged_data(type_id, type_version, data),
        )

    def _append_parallel_execution(self, event: Event) -> None:
        data: dict = {}
        if isinstance(event, ParallelStarted):
            data = {
                "node_id": event.node_id,
                "branch_count": event.branch_count,
                "status": "started",
            }
        elif isinstance(event, ParallelCompleted):
            data = {
                "node_id": event.node_id,
                "branch_count": 0,
                "success_count": event.success_count,
                "failure_count": event.failure_count,
                "duration_ms": event.duration_ms,
                "status": "completed",
            }

        type_id = "dev.orchestra.ParallelExecution"
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=1,
            data=to_tagged_data(type_id, 1, data),
        )

    def _append_worktree_event(self, event: Event) -> None:
        data: dict = {}
        if isinstance(event, WorktreeCreated):
            data = {
                "repo_name": event.repo_name,
                "branch_id": event.branch_id,
                "worktree_path": event.worktree_path,
                "worktree_branch": event.worktree_branch,
                "status": "created",
            }
        elif isinstance(event, WorktreeMerged):
            data = {
                "repo_name": event.repo_name,
                "branch_ids": event.branch_ids,
                "merged_sha": event.merged_sha,
                "status": "merged",
            }

        type_id = "dev.orchestra.WorktreeEvent"
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=1,
            data=to_tagged_data(type_id, 1, data),
        )

    def _append_checkpoint(self, event: CheckpointSaved) -> None:
        type_id = "dev.orchestra.Checkpoint"
        type_version = 3  # v3 adds workspace_snapshot
        data: dict = {
            "current_node": event.node_id,
            "completed_nodes": event.completed_nodes,
            "context_snapshot": event.context_snapshot,
            "retry_counters": event.retry_counters,
            "next_node_id": event.next_node_id,
            "visited_outcomes": event.visited_outcomes,
            "reroute_count": event.reroute_count,
            "workspace_snapshot": event.workspace_snapshot,
        }
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=type_version,
            data=to_tagged_data(type_id, type_version, data),
        )
