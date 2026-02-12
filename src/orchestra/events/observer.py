from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import typer

from orchestra.events.types import (
    CheckpointSaved,
    Event,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    StageCompleted,
    StageFailed,
    StageRetrying,
    StageStarted,
)

from orchestra.storage.type_bundle import to_tagged_data

if TYPE_CHECKING:
    from orchestra.storage.cxdb_client import CxdbClient


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
        elif isinstance(event, CheckpointSaved):
            typer.echo(f"  [Checkpoint] Saved at: {event.node_id}")


class CxdbObserver:
    def __init__(self, client: CxdbClient, context_id: str) -> None:
        self._client = client
        self._context_id = context_id

    def on_event(self, event: Event) -> None:
        if isinstance(event, (PipelineStarted, PipelineCompleted, PipelineFailed)):
            self._append_pipeline_lifecycle(event)
        elif isinstance(event, (StageStarted, StageCompleted, StageFailed, StageRetrying)):
            self._append_node_execution(event)
        elif isinstance(event, CheckpointSaved):
            self._append_checkpoint(event)

    def _append_pipeline_lifecycle(self, event: Event) -> None:
        data: dict = {}
        if isinstance(event, PipelineStarted):
            data = {
                "pipeline_name": event.pipeline_name,
                "goal": event.goal,
                "status": "started",
                "session_display_id": event.session_display_id,
            }
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

        type_id = "dev.orchestra.PipelineLifecycle"
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=1,
            data=to_tagged_data(type_id, 1, data),
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

    def _append_checkpoint(self, event: CheckpointSaved) -> None:
        type_id = "dev.orchestra.Checkpoint"
        data = {
            "current_node": event.node_id,
            "completed_nodes": event.completed_nodes,
            "context_snapshot": event.context_snapshot,
            "retry_counters": event.retry_counters,
        }
        self._client.append_turn(
            context_id=self._context_id,
            type_id=type_id,
            type_version=1,
            data=to_tagged_data(type_id, 1, data),
        )
