import json

from orchestra.cli.status import _aggregate_detail


def _make_agent_turn(node_id: str, tokens_in: int = 0, tokens_out: int = 0, tool_calls: list | None = None) -> dict:
    data: dict = {
        "node_id": node_id,
        "turn_number": 1,
        "token_usage": {"input": tokens_in, "output": tokens_out},
    }
    if tool_calls:
        data["tool_calls"] = json.dumps(tool_calls)
    return {
        "type_id": "dev.orchestra.AgentTurn",
        "data": data,
    }


def _make_node_execution(node_id: str, status: str = "completed", duration_ms: int = 0) -> dict:
    return {
        "type_id": "dev.orchestra.NodeExecution",
        "data": {
            "node_id": node_id,
            "status": status,
            "duration_ms": duration_ms,
        },
    }


class TestAggregateDetail:
    def test_token_usage_aggregated_from_agent_turns(self):
        turns = [
            _make_agent_turn("reviewer", tokens_in=100, tokens_out=50),
            _make_agent_turn("reviewer", tokens_in=200, tokens_out=75),
            _make_agent_turn("synthesizer", tokens_in=300, tokens_out=100),
        ]

        details = _aggregate_detail(turns)
        by_node = {d["node_id"]: d for d in details}

        assert by_node["reviewer"]["tokens_in"] == 300
        assert by_node["reviewer"]["tokens_out"] == 125
        assert by_node["synthesizer"]["tokens_in"] == 300
        assert by_node["synthesizer"]["tokens_out"] == 100

    def test_timing_from_node_execution_turns(self):
        turns = [
            _make_node_execution("reviewer", status="started"),
            _make_node_execution("reviewer", status="completed", duration_ms=1500),
            _make_node_execution("synthesizer", status="completed", duration_ms=2000),
        ]

        details = _aggregate_detail(turns)
        by_node = {d["node_id"]: d for d in details}

        assert by_node["reviewer"]["duration_ms"] == 1500
        assert by_node["synthesizer"]["duration_ms"] == 2000

    def test_tool_invocation_counts_from_agent_turns(self):
        turns = [
            _make_agent_turn("coder", tool_calls=[
                {"name": "write_file", "args": {}},
                {"name": "read_file", "args": {}},
            ]),
            _make_agent_turn("coder", tool_calls=[
                {"name": "write_file", "args": {}},
            ]),
            _make_agent_turn("reviewer"),
        ]

        details = _aggregate_detail(turns)
        by_node = {d["node_id"]: d for d in details}

        assert by_node["coder"]["tools"] == 3
        assert by_node["reviewer"]["tools"] == 0

    def test_combined_agent_and_execution_data(self):
        turns = [
            _make_node_execution("analyst", status="started"),
            _make_agent_turn("analyst", tokens_in=500, tokens_out=200, tool_calls=[
                {"name": "search", "args": {}},
            ]),
            _make_node_execution("analyst", status="completed", duration_ms=3000),
        ]

        details = _aggregate_detail(turns)
        assert len(details) == 1
        d = details[0]
        assert d["node_id"] == "analyst"
        assert d["tokens_in"] == 500
        assert d["tokens_out"] == 200
        assert d["tools"] == 1
        assert d["duration_ms"] == 3000
        assert d["status"] == "completed"

    def test_empty_turns_returns_empty(self):
        details = _aggregate_detail([])
        assert details == []

    def test_non_matching_turn_types_ignored(self):
        turns = [
            {"type_id": "dev.orchestra.PipelineLifecycle", "data": {"status": "started"}},
            {"type_id": "dev.orchestra.Checkpoint", "data": {"current_node": "n1"}},
        ]

        details = _aggregate_detail(turns)
        assert details == []

    def test_multiple_nodes_separated(self):
        turns = [
            _make_agent_turn("node_a", tokens_in=100, tokens_out=50),
            _make_agent_turn("node_b", tokens_in=200, tokens_out=75),
            _make_node_execution("node_a", status="completed", duration_ms=1000),
            _make_node_execution("node_b", status="completed", duration_ms=2000),
        ]

        details = _aggregate_detail(turns)
        assert len(details) == 2
        by_node = {d["node_id"]: d for d in details}
        assert by_node["node_a"]["tokens_in"] == 100
        assert by_node["node_b"]["tokens_in"] == 200
        assert by_node["node_a"]["duration_ms"] == 1000
        assert by_node["node_b"]["duration_ms"] == 2000

    def test_status_takes_latest_value(self):
        turns = [
            _make_node_execution("node_a", status="started"),
            _make_node_execution("node_a", status="completed", duration_ms=500),
        ]

        details = _aggregate_detail(turns)
        assert details[0]["status"] == "completed"
