from __future__ import annotations

from typing import Any

from orchestra.models.agent_turn import AgentTurn
from orchestra.workspace.on_turn import build_on_turn_callback


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


class MockWorkspaceManager:
    def __init__(self) -> None:
        self.turns: list[AgentTurn] = []

    def on_turn_callback(self, turn: AgentTurn) -> None:
        self.turns.append(turn)


class TestBuildOnTurnCallback:
    def test_without_workspace_emits_event(self) -> None:
        emitter = RecordingEmitter()
        callback = build_on_turn_callback(emitter, workspace_manager=None)

        turn = AgentTurn(turn_number=1, model="test", provider="p")
        callback(turn)

        assert len(emitter.events) == 1
        event_type, data = emitter.events[0]
        assert event_type == "AgentTurnCompleted"
        assert data["turn_number"] == 1
        assert data["model"] == "test"
        assert data["git_sha"] == ""

    def test_with_workspace_delegates_to_manager(self) -> None:
        emitter = RecordingEmitter()
        manager = MockWorkspaceManager()
        callback = build_on_turn_callback(emitter, workspace_manager=manager)

        turn = AgentTurn(turn_number=2, model="m", provider="p")
        callback(turn)

        assert len(manager.turns) == 1
        assert manager.turns[0].turn_number == 2
        # Manager handles events, so emitter should not be called directly
        assert len(emitter.events) == 0

    def test_without_workspace_includes_all_fields(self) -> None:
        emitter = RecordingEmitter()
        callback = build_on_turn_callback(emitter, workspace_manager=None)

        turn = AgentTurn(
            turn_number=3,
            model="claude",
            provider="anthropic",
            files_written=["a.py"],
            token_usage={"input": 10},
        )
        callback(turn)

        data = emitter.events[0][1]
        assert data["files_written"] == ["a.py"]
        assert data["token_usage"] == {"input": 10}
        assert data["commit_message"] == ""
