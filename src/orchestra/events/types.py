from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str


class PipelineStarted(Event):
    event_type: str = "PipelineStarted"
    pipeline_name: str
    goal: str = ""
    session_display_id: str = ""
    dot_file_path: str = ""
    graph_hash: str = ""


class PipelineCompleted(Event):
    event_type: str = "PipelineCompleted"
    pipeline_name: str
    duration_ms: int = 0
    session_display_id: str = ""


class PipelineFailed(Event):
    event_type: str = "PipelineFailed"
    pipeline_name: str
    error: str = ""
    session_display_id: str = ""


class StageStarted(Event):
    event_type: str = "StageStarted"
    node_id: str
    handler_type: str


class StageCompleted(Event):
    event_type: str = "StageCompleted"
    node_id: str
    handler_type: str
    status: str = ""
    duration_ms: int = 0
    prompt: str = ""
    response: str = ""
    outcome: str = ""


class StageFailed(Event):
    event_type: str = "StageFailed"
    node_id: str
    handler_type: str
    error: str = ""


class StageRetrying(Event):
    event_type: str = "StageRetrying"
    node_id: str
    attempt: int = 0
    max_attempts: int = 0
    delay_ms: int = 0


class CheckpointSaved(Event):
    event_type: str = "CheckpointSaved"
    node_id: str
    completed_nodes: list[str] = Field(default_factory=list)
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    retry_counters: dict[str, Any] = Field(default_factory=dict)
    next_node_id: str = ""
    visited_outcomes: dict[str, str] = Field(default_factory=dict)
    reroute_count: int = 0


class PipelinePaused(Event):
    event_type: str = "PipelinePaused"
    pipeline_name: str
    session_display_id: str = ""
    checkpoint_node_id: str = ""


class AgentTurnCompleted(Event):
    event_type: str = "AgentTurnCompleted"
    node_id: str
    turn_number: int = 0
    model: str = ""
    provider: str = ""
    messages: str = ""
    tool_calls: str = ""
    files_written: list[str] = Field(default_factory=list)
    token_usage: dict[str, int] = Field(default_factory=dict)
    agent_state: str = ""


class HumanInteraction(Event):
    event_type: str = "HumanInteraction"
    node_id: str
    question_text: str = ""
    question_type: str = ""
    answer_value: str = ""
    answer_text: str = ""
    selected_option_key: str = ""


EVENT_TYPE_MAP: dict[str, type[Event]] = {
    "PipelineStarted": PipelineStarted,
    "PipelineCompleted": PipelineCompleted,
    "PipelineFailed": PipelineFailed,
    "PipelinePaused": PipelinePaused,
    "StageStarted": StageStarted,
    "StageCompleted": StageCompleted,
    "StageFailed": StageFailed,
    "StageRetrying": StageRetrying,
    "CheckpointSaved": CheckpointSaved,
    "AgentTurnCompleted": AgentTurnCompleted,
    "HumanInteraction": HumanInteraction,
}
