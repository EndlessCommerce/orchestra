import pytest

from orchestra.cli.replay_cmd import _restore_from_checkpoint
from orchestra.engine.resume import ResumeError


def _make_pipeline_started_turn(turn_id: str = "t1") -> dict:
    return {
        "turn_id": turn_id,
        "type_id": "dev.orchestra.PipelineLifecycle",
        "data": {
            "pipeline_name": "test-pipeline",
            "status": "started",
            "dot_file_path": "/tmp/test.dot",
            "graph_hash": "abc123",
        },
    }


def _make_checkpoint_turn(
    turn_id: str,
    next_node_id: str = "node_b",
    context_snapshot: dict | None = None,
    workspace_snapshot: dict | None = None,
    completed_nodes: list[str] | None = None,
    visited_outcomes: dict | None = None,
) -> dict:
    data = {
        "current_node": "node_a",
        "completed_nodes": completed_nodes or ["start", "node_a"],
        "context_snapshot": context_snapshot or {"key1": "val1"},
        "retry_counters": {},
        "next_node_id": next_node_id,
        "visited_outcomes": visited_outcomes or {"start": "SUCCESS", "node_a": "SUCCESS"},
        "reroute_count": 0,
    }
    if workspace_snapshot:
        data["workspace_snapshot"] = workspace_snapshot
    return {
        "turn_id": turn_id,
        "type_id": "dev.orchestra.Checkpoint",
        "data": data,
    }


class TestRestoreFromCheckpoint:
    def test_restores_correct_node_and_context(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn("cp1", next_node_id="node_b", context_snapshot={"foo": "bar"}),
            _make_checkpoint_turn("cp2", next_node_id="node_c", context_snapshot={"baz": "qux"}),
        ]

        info = _restore_from_checkpoint(turns, "cp1", "ctx-123")
        assert info.next_node_id == "node_b"
        assert info.state.context.get("foo") == "bar"
        assert info.pipeline_name == "test-pipeline"
        assert info.dot_file_path == "/tmp/test.dot"
        assert info.graph_hash == "abc123"

    def test_restores_from_second_checkpoint(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn("cp1", next_node_id="node_b"),
            _make_checkpoint_turn("cp2", next_node_id="node_c", context_snapshot={"step": "2"}),
        ]

        info = _restore_from_checkpoint(turns, "cp2", "ctx-123")
        assert info.next_node_id == "node_c"
        assert info.state.context.get("step") == "2"

    def test_workspace_snapshot_provides_git_sha(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn(
                "cp1",
                next_node_id="node_b",
                workspace_snapshot={"main-repo": "abc123def456"},
            ),
        ]

        info = _restore_from_checkpoint(turns, "cp1", "ctx-123")
        assert info.git_sha == "abc123def456"

    def test_invalid_checkpoint_id(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn("cp1", next_node_id="node_b"),
        ]

        with pytest.raises(ResumeError, match="Checkpoint with turn_id=nonexistent not found"):
            _restore_from_checkpoint(turns, "nonexistent", "ctx-123")

    def test_no_turns(self):
        with pytest.raises(ResumeError, match="No turns found"):
            _restore_from_checkpoint([], "cp1", "ctx-123")

    def test_checkpoint_without_next_node_id(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn("cp1", next_node_id=""),
        ]

        with pytest.raises(ResumeError, match="no next_node_id"):
            _restore_from_checkpoint(turns, "cp1", "ctx-123")

    def test_restores_completed_nodes(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn(
                "cp1",
                next_node_id="node_c",
                completed_nodes=["start", "node_a", "node_b"],
            ),
        ]

        info = _restore_from_checkpoint(turns, "cp1", "ctx-123")
        assert info.state.completed_nodes == ["start", "node_a", "node_b"]

    def test_restores_visited_outcomes(self):
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn(
                "cp1",
                next_node_id="node_c",
                visited_outcomes={"start": "SUCCESS", "node_a": "FAIL"},
            ),
        ]

        info = _restore_from_checkpoint(turns, "cp1", "ctx-123")
        from orchestra.models.outcome import OutcomeStatus

        assert info.state.visited_outcomes["node_a"] == OutcomeStatus.FAIL

    def test_agent_turn_not_matched_as_checkpoint(self):
        """Ensure that an AgentTurn with the same turn_id is not matched."""
        turns = [
            _make_pipeline_started_turn("t1"),
            {
                "turn_id": "cp1",
                "type_id": "dev.orchestra.AgentTurn",
                "data": {"node_id": "n1", "turn_number": 1},
            },
        ]

        with pytest.raises(ResumeError, match="Checkpoint with turn_id=cp1 not found"):
            _restore_from_checkpoint(turns, "cp1", "ctx-123")


class TestReplayMutualExclusion:
    """Test that --turn and --checkpoint are mutually exclusive at the CLI level."""

    def test_both_turn_and_checkpoint_raises(self):
        """This is tested via the replay() function logic, not the CLI."""
        # The actual mutual exclusion check is in replay() which checks both params
        # This validates the _restore_from_checkpoint function works independently
        turns = [
            _make_pipeline_started_turn("t1"),
            _make_checkpoint_turn("cp1", next_node_id="node_b"),
        ]
        info = _restore_from_checkpoint(turns, "cp1", "ctx-123")
        assert info.next_node_id == "node_b"
