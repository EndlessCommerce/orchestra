from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.engine.resume import ResumeError, _extract_turn_data, _extract_type_id
from orchestra.engine.runner import _RunState
from orchestra.models.context import Context
from orchestra.models.outcome import OutcomeStatus


@dataclass
class TurnResumeInfo:
    """State needed to resume from a specific agent turn."""

    state: _RunState
    next_node_id: str
    turn_number: int
    git_sha: str
    prior_messages: list[dict[str, Any]]
    pipeline_name: str
    dot_file_path: str
    graph_hash: str
    context_id: str


def restore_from_turn(
    turns: list[dict[str, Any]], turn_id: str, context_id: str
) -> TurnResumeInfo:
    """Restore pipeline state from a specific agent turn.

    Finds the specified AgentTurn, finds the most recent Checkpoint before it,
    restores pipeline state from that Checkpoint, and collects prior AgentTurns
    for the same node to reconstruct message history.

    Args:
        turns: All turns from the CXDB context.
        turn_id: The turn_id of the AgentTurn to resume from.
        context_id: The CXDB context ID.

    Returns:
        TurnResumeInfo with pipeline state, git sha, and prior messages.
    """
    if not turns:
        raise ResumeError("No turns found in session")

    # Find PipelineStarted for metadata
    pipeline_name = ""
    dot_file_path = ""
    graph_hash = ""
    for turn in turns:
        data = _extract_turn_data(turn)
        type_id = _extract_type_id(turn)
        if type_id == "dev.orchestra.PipelineLifecycle" and data.get("status") == "started":
            pipeline_name = data.get("pipeline_name", "")
            dot_file_path = data.get("dot_file_path", "")
            graph_hash = data.get("graph_hash", "")
            break

    # Find the target AgentTurn
    target_turn_data: dict[str, Any] | None = None
    target_turn_index: int | None = None
    for i, turn in enumerate(turns):
        tid = str(turn.get("turn_id", ""))
        if tid == turn_id and _extract_type_id(turn) == "dev.orchestra.AgentTurn":
            target_turn_data = _extract_turn_data(turn)
            target_turn_index = i
            break

    if target_turn_data is None:
        raise ResumeError(f"AgentTurn with turn_id={turn_id} not found")

    target_node_id = target_turn_data.get("node_id", "")
    target_turn_number = int(target_turn_data.get("turn_number", 0))
    git_sha = target_turn_data.get("git_sha", "")

    # Find the most recent Checkpoint before the target turn
    checkpoint_data: dict[str, Any] | None = None
    for i in range(target_turn_index - 1, -1, -1):
        if _extract_type_id(turns[i]) == "dev.orchestra.Checkpoint":
            checkpoint_data = _extract_turn_data(turns[i])
            break

    if checkpoint_data is None:
        raise ResumeError("No checkpoint found before the target turn")

    # Restore _RunState from checkpoint
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

    # Collect prior AgentTurn messages for the same node (for conversation reconstruction)
    prior_messages: list[dict[str, Any]] = []
    for i in range(target_turn_index + 1):
        turn = turns[i]
        if _extract_type_id(turn) != "dev.orchestra.AgentTurn":
            continue
        turn_data = _extract_turn_data(turn)
        if turn_data.get("node_id") != target_node_id:
            continue
        messages_raw = turn_data.get("messages", "")
        if messages_raw:
            import json

            try:
                msgs = json.loads(messages_raw) if isinstance(messages_raw, str) else messages_raw
                if isinstance(msgs, list):
                    prior_messages.extend(msgs)
            except (json.JSONDecodeError, TypeError):
                pass

    # If git_sha is empty, find the most recent non-empty git_sha from prior turns
    if not git_sha:
        for i in range(target_turn_index - 1, -1, -1):
            if _extract_type_id(turns[i]) == "dev.orchestra.AgentTurn":
                prior_data = _extract_turn_data(turns[i])
                prior_sha = prior_data.get("git_sha", "")
                if prior_sha:
                    git_sha = prior_sha
                    break

    return TurnResumeInfo(
        state=state,
        next_node_id=target_node_id,
        turn_number=target_turn_number,
        git_sha=git_sha,
        prior_messages=prior_messages,
        pipeline_name=pipeline_name,
        dot_file_path=dot_file_path,
        graph_hash=graph_hash,
        context_id=context_id,
    )
