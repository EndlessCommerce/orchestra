from orchestra.models.agent_turn import AgentTurn


class TestAgentTurnConstruction:
    def test_minimal_construction(self):
        turn = AgentTurn(turn_number=1)
        assert turn.turn_number == 1
        assert turn.model == ""
        assert turn.provider == ""
        assert turn.messages == []
        assert turn.tool_calls == []
        assert turn.files_written == []
        assert turn.token_usage == {}
        assert turn.agent_state == {}

    def test_full_construction(self):
        turn = AgentTurn(
            turn_number=3,
            model="claude-opus-4-20250514",
            provider="anthropic",
            messages=[{"role": "assistant", "content": "Hello"}],
            tool_calls=[{"name": "read-file", "args": {"path": "a.py"}}],
            files_written=["src/main.py"],
            token_usage={"input": 100, "output": 50},
            agent_state={"step": "review"},
        )
        assert turn.turn_number == 3
        assert turn.model == "claude-opus-4-20250514"
        assert turn.provider == "anthropic"
        assert turn.messages == [{"role": "assistant", "content": "Hello"}]
        assert turn.tool_calls == [{"name": "read-file", "args": {"path": "a.py"}}]
        assert turn.files_written == ["src/main.py"]
        assert turn.token_usage == {"input": 100, "output": 50}
        assert turn.agent_state == {"step": "review"}


class TestAgentTurnSerialization:
    def test_to_dict(self):
        turn = AgentTurn(
            turn_number=1,
            model="gpt-4o",
            provider="openai",
            messages=[{"role": "user", "content": "Hi"}],
            tool_calls=[],
            files_written=["out.txt"],
            token_usage={"input": 10},
            agent_state={},
        )
        result = turn.to_dict()
        assert result == {
            "turn_number": 1,
            "model": "gpt-4o",
            "provider": "openai",
            "messages": [{"role": "user", "content": "Hi"}],
            "tool_calls": [],
            "files_written": ["out.txt"],
            "token_usage": {"input": 10},
            "agent_state": {},
        }

    def test_to_dict_defaults(self):
        turn = AgentTurn(turn_number=0)
        result = turn.to_dict()
        assert result["turn_number"] == 0
        assert result["messages"] == []
        assert result["files_written"] == []

    def test_default_lists_are_independent(self):
        turn1 = AgentTurn(turn_number=1)
        turn2 = AgentTurn(turn_number=2)
        turn1.files_written.append("a.py")
        assert turn2.files_written == []
