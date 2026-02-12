from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SessionInfo:
    context_id: str
    display_id: str
    pipeline_name: str
    status: str  # "running", "paused", "completed", "failed"
    turn_count: int


def derive_session_status(turns: list[dict[str, Any]]) -> str:
    """Derive session status from CXDB context turns.

    Status rules (based on head turn type):
    - Head turn is PipelineLifecycle with status="paused" → paused
    - Head turn is PipelineLifecycle with status="completed" → completed
    - Head turn is PipelineLifecycle with status="failed" → failed
    - Head turn is Checkpoint (no terminal lifecycle) → paused (interrupted)
    - Otherwise → running
    """
    if not turns:
        return "unknown"

    # Scan from the end for the most significant turn
    for turn in reversed(turns):
        type_id = turn.get("type_id", "")
        data = turn.get("data", {})

        if type_id == "dev.orchestra.PipelineLifecycle":
            status = data.get("status", "")
            if status == "paused":
                return "paused"
            if status == "completed":
                return "completed"
            if status == "failed":
                return "failed"
            # "started" as head turn means still running
            if status == "started":
                return "running"

        if type_id == "dev.orchestra.Checkpoint":
            # Checkpoint as head turn without a terminal lifecycle means
            # the pipeline was interrupted (crashed or killed without graceful pause)
            return "paused"

        if type_id == "dev.orchestra.NodeExecution":
            # Node execution as head turn means still running
            return "running"

    return "unknown"


def extract_session_info(
    context_id: str, turns: list[dict[str, Any]]
) -> SessionInfo:
    """Extract session metadata from CXDB context turns."""
    display_id = ""
    pipeline_name = ""

    for turn in turns:
        type_id = turn.get("type_id", "")
        data = turn.get("data", {})

        if type_id == "dev.orchestra.PipelineLifecycle":
            status = data.get("status", "")
            if status == "started":
                pipeline_name = data.get("pipeline_name", "")
                display_id = data.get("session_display_id", "")
                break

    return SessionInfo(
        context_id=context_id,
        display_id=display_id,
        pipeline_name=pipeline_name,
        status=derive_session_status(turns),
        turn_count=len(turns),
    )
