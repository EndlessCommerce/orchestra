from unittest.mock import MagicMock

from orchestra.events.observer import CxdbObserver
from orchestra.events.types import AgentTurnCompleted
from orchestra.storage.type_bundle import ORCHESTRA_TYPE_BUNDLE, to_tagged_data


class TestAgentTurnCxdbType:
    def test_agent_turn_type_registered(self):
        types = ORCHESTRA_TYPE_BUNDLE["types"]
        assert "dev.orchestra.AgentTurn" in types

    def test_agent_turn_v1_fields(self):
        fields = ORCHESTRA_TYPE_BUNDLE["types"]["dev.orchestra.AgentTurn"]["versions"]["1"]["fields"]
        field_names = {f["name"] for f in fields.values()}
        assert "turn_number" in field_names
        assert "node_id" in field_names
        assert "model" in field_names
        assert "provider" in field_names
        assert "messages" in field_names
        assert "tool_calls" in field_names
        assert "files_written" in field_names
        assert "token_usage" in field_names
        assert "agent_state" in field_names

    def test_to_tagged_data(self):
        data = {
            "turn_number": 1,
            "node_id": "write",
            "model": "gpt-4o",
        }
        tagged = to_tagged_data("dev.orchestra.AgentTurn", 1, data)
        assert isinstance(tagged, dict)
        assert all(isinstance(k, int) for k in tagged.keys())


class TestCxdbObserverAgentTurn:
    def test_persists_agent_turn_completed(self):
        mock_client = MagicMock()
        observer = CxdbObserver(client=mock_client, context_id="ctx-123")

        event = AgentTurnCompleted(
            node_id="write",
            turn_number=1,
            model="claude-opus-4-20250514",
            provider="anthropic",
            messages='[{"role": "assistant"}]',
            tool_calls="[]",
            files_written=["out.py"],
            token_usage={"input": 100, "output": 50},
            agent_state="{}",
        )
        observer.on_event(event)

        mock_client.append_turn.assert_called_once()
        call_kwargs = mock_client.append_turn.call_args
        assert call_kwargs.kwargs["type_id"] == "dev.orchestra.AgentTurn"
        assert call_kwargs.kwargs["type_version"] == 1
        assert call_kwargs.kwargs["context_id"] == "ctx-123"

    def test_multiple_turns_persisted(self):
        mock_client = MagicMock()
        observer = CxdbObserver(client=mock_client, context_id="ctx-123")

        for i in range(3):
            event = AgentTurnCompleted(
                node_id="code",
                turn_number=i + 1,
                model="gpt-4o",
            )
            observer.on_event(event)

        assert mock_client.append_turn.call_count == 3
