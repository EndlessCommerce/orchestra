from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import blake3

from orchestra.engine.runner import _RunState
from orchestra.models.context import Context
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import parse_dot
from orchestra.transforms.variable_expansion import expand_variables


@dataclass
class ResumeInfo:
    """All the state needed to resume a pipeline from a checkpoint."""

    state: _RunState
    next_node_id: str
    pipeline_name: str
    dot_file_path: str
    graph_hash: str
    context_id: str


class ResumeError(Exception):
    pass


def restore_from_turns(turns: list[dict[str, Any]], context_id: str) -> ResumeInfo:
    """Read CXDB turns and extract resume state from the latest checkpoint.

    Args:
        turns: List of turns from CXDB get_turns (in append order).
        context_id: The CXDB context ID for this session.

    Returns:
        ResumeInfo with all state needed to resume.

    Raises:
        ResumeError: If the session cannot be resumed.
    """
    if not turns:
        raise ResumeError("No turns found in session")

    # Find PipelineStarted turn for metadata
    pipeline_name = ""
    dot_file_path = ""
    graph_hash = ""
    for turn in turns:
        data = _extract_turn_data(turn)
        type_id = _extract_type_id(turn)
        if type_id == "dev.orchestra.PipelineLifecycle":
            status = data.get("status", "")
            if status == "started":
                pipeline_name = data.get("pipeline_name", "")
                dot_file_path = data.get("dot_file_path", "")
                graph_hash = data.get("graph_hash", "")
            elif status == "completed":
                raise ResumeError("Session already completed — cannot resume")
            elif status == "failed":
                raise ResumeError("Session failed — cannot resume")

    # Find latest Checkpoint turn (last one in the list)
    checkpoint_data: dict[str, Any] | None = None
    for turn in reversed(turns):
        type_id = _extract_type_id(turn)
        if type_id == "dev.orchestra.Checkpoint":
            checkpoint_data = _extract_turn_data(turn)
            break

    if checkpoint_data is None:
        raise ResumeError("No checkpoint found in session")

    next_node_id = checkpoint_data.get("next_node_id", "")
    if not next_node_id:
        raise ResumeError("Checkpoint has no next_node_id — pipeline may have terminated")

    # Restore _RunState
    ctx = Context()
    for key, value in checkpoint_data.get("context_snapshot", {}).items():
        ctx.set(key, value)

    visited_raw = checkpoint_data.get("visited_outcomes", {})
    visited_outcomes: dict[str, OutcomeStatus] = {}
    for node_id, status_str in visited_raw.items():
        visited_outcomes[node_id] = OutcomeStatus(status_str)

    state = _RunState(
        context=ctx,
        completed_nodes=list(checkpoint_data.get("completed_nodes", [])),
        visited_outcomes=visited_outcomes,
        retry_counters=dict(checkpoint_data.get("retry_counters", {})),
        reroute_count=int(checkpoint_data.get("reroute_count", 0)),
    )

    return ResumeInfo(
        state=state,
        next_node_id=next_node_id,
        pipeline_name=pipeline_name,
        dot_file_path=dot_file_path,
        graph_hash=graph_hash,
        context_id=context_id,
    )


def verify_graph_hash(dot_file_path: str, expected_hash: str) -> None:
    """Verify the DOT file hasn't changed since the original run.

    Raises:
        ResumeError: If the file is missing or hash doesn't match.
    """
    path = Path(dot_file_path)
    if not path.exists():
        raise ResumeError(f"DOT file not found: {dot_file_path}")

    current_hash = blake3.blake3(path.read_bytes()).hexdigest()
    if expected_hash and current_hash != expected_hash:
        raise ResumeError(
            f"DOT file has been modified since the original run "
            f"(expected hash {expected_hash[:12]}..., got {current_hash[:12]}...)"
        )


def load_graph_for_resume(dot_file_path: str):
    """Parse and transform the DOT file for resume execution."""
    path = Path(dot_file_path)
    source = path.read_text()
    graph = parse_dot(source)
    return expand_variables(graph)


def _extract_turn_data(turn: dict[str, Any]) -> dict[str, Any]:
    """Extract the data payload from a CXDB turn."""
    # CXDB may return data under different keys depending on the view
    data = turn.get("data", {})
    if isinstance(data, dict):
        return data
    return {}


def _extract_type_id(turn: dict[str, Any]) -> str:
    """Extract the type_id from a CXDB turn."""
    return turn.get("type_id", "")
