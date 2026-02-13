from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from orchestra.models.agent_turn import AgentTurn

if TYPE_CHECKING:
    from orchestra.workspace.workspace_manager import EventEmitter, WorkspaceManager


def build_on_turn_callback(
    event_emitter: EventEmitter,
    workspace_manager: WorkspaceManager | None = None,
):
    if workspace_manager is not None:
        return workspace_manager.on_turn_callback

    def _emit_only(turn: AgentTurn) -> None:
        event_emitter.emit(
            "AgentTurnCompleted",
            node_id="unknown",
            turn_number=turn.turn_number,
            model=turn.model,
            provider=turn.provider,
            messages=json.dumps(turn.messages) if turn.messages else "",
            tool_calls=json.dumps(turn.tool_calls) if turn.tool_calls else "",
            files_written=turn.files_written,
            token_usage=turn.token_usage,
            agent_state=json.dumps(turn.agent_state) if turn.agent_state else "",
            git_sha="",
            commit_message="",
        )

    return _emit_only
