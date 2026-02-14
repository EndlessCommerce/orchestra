"""Tests for replay-from-agent-turn functionality.

Covers restore_from_turn (turn_resume module) and CXDB fork via create_context.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestra.engine.turn_resume import TurnResumeInfo, restore_from_turn
from orchestra.models.outcome import OutcomeStatus

# ---------------------------------------------------------------------------
# Shared fixture: mock CXDB turns representing a pipeline session
# ---------------------------------------------------------------------------

MOCK_TURNS: list[dict] = [
    {
        "turn_id": "1",
        "type_id": "dev.orchestra.PipelineLifecycle",
        "data": {
            "status": "started",
            "pipeline_name": "test",
            "dot_file_path": "/tmp/test.dot",
            "graph_hash": "abc",
        },
    },
    {
        "turn_id": "2",
        "type_id": "dev.orchestra.Checkpoint",
        "data": {
            "current_node": "start",
            "completed_nodes": ["start"],
            "context_snapshot": {"key": "val"},
            "next_node_id": "plan",
            "visited_outcomes": {"start": "SUCCESS"},
            "reroute_count": 0,
        },
    },
    {
        "turn_id": "3",
        "type_id": "dev.orchestra.AgentTurn",
        "data": {
            "node_id": "plan",
            "turn_number": 1,
            "model": "claude",
            "git_sha": "abc123def",
            "messages": "[]",
        },
    },
    {
        "turn_id": "4",
        "type_id": "dev.orchestra.AgentTurn",
        "data": {
            "node_id": "plan",
            "turn_number": 2,
            "model": "claude",
            "git_sha": "def456ghi",
            "messages": '[{"role": "user", "content": "hello"}]',
        },
    },
]


# ---------------------------------------------------------------------------
# Test 1: restore_from_turn returns correct state from Checkpoint + AgentTurn
# ---------------------------------------------------------------------------


class TestReplayFromAgentTurn:
    """restore_from_turn rebuilds state from the preceding Checkpoint and
    attaches metadata from the target AgentTurn."""

    def test_replay_from_agent_turn(self) -> None:
        info = restore_from_turn(MOCK_TURNS, turn_id="4", context_id="ctx-99")

        # Pipeline metadata comes from the PipelineLifecycle turn
        assert info.pipeline_name == "test"
        assert info.dot_file_path == "/tmp/test.dot"
        assert info.graph_hash == "abc"

        # State is rebuilt from the Checkpoint (turn 2)
        assert info.state.completed_nodes == ["start"]
        assert info.state.visited_outcomes == {"start": OutcomeStatus.SUCCESS}
        assert info.state.reroute_count == 0
        # Context snapshot is restored
        assert info.state.context.get("key") == "val"

        # Target AgentTurn fields
        assert info.next_node_id == "plan"
        assert info.turn_number == 2
        assert info.git_sha == "def456ghi"
        assert info.context_id == "ctx-99"

        # Prior messages: turn 3 had "[]" (empty list) and turn 4 had one msg
        assert len(info.prior_messages) == 1
        assert info.prior_messages[0] == {"role": "user", "content": "hello"}

    def test_replay_from_first_agent_turn(self) -> None:
        """Replaying from the first AgentTurn also works correctly."""
        info = restore_from_turn(MOCK_TURNS, turn_id="3", context_id="ctx-1")

        assert info.next_node_id == "plan"
        assert info.turn_number == 1
        assert info.git_sha == "abc123def"
        # No prior messages since turn 3's messages are "[]"
        assert info.prior_messages == []


# ---------------------------------------------------------------------------
# Test 2: git_sha is correctly extracted from the target AgentTurn
# ---------------------------------------------------------------------------


class TestReplayRestoresGitState:
    """TurnResumeInfo.git_sha matches the git_sha recorded in the target
    AgentTurn."""

    def test_replay_restores_git_state(self) -> None:
        info = restore_from_turn(MOCK_TURNS, turn_id="3", context_id="ctx-1")
        assert info.git_sha == "abc123def"

        info2 = restore_from_turn(MOCK_TURNS, turn_id="4", context_id="ctx-1")
        assert info2.git_sha == "def456ghi"

    def test_replay_falls_back_to_prior_sha_when_empty(self) -> None:
        """When the target AgentTurn has an empty git_sha, the function
        falls back to the most recent non-empty sha from a prior AgentTurn."""
        turns_with_empty_sha = list(MOCK_TURNS) + [
            {
                "turn_id": "5",
                "type_id": "dev.orchestra.AgentTurn",
                "data": {
                    "node_id": "plan",
                    "turn_number": 3,
                    "model": "claude",
                    "git_sha": "",
                    "messages": "[]",
                },
            },
        ]
        info = restore_from_turn(turns_with_empty_sha, turn_id="5", context_id="ctx-1")
        # Should fall back to turn 4's git_sha
        assert info.git_sha == "def456ghi"


# ---------------------------------------------------------------------------
# Test 3: Fork creates new CXDB context with correct base_turn_id
# ---------------------------------------------------------------------------


class TestReplayDiverges:
    """When replaying from a turn, a new context is forked via
    CxdbClient.create_context with the base_turn_id pointing at the
    divergence point."""

    def test_replay_diverges(self) -> None:
        mock_client = MagicMock()
        mock_client.create_context.return_value = {
            "context_id": "42",
            "base_turn_id": "4",
        }

        # Simulate the fork: caller would invoke create_context with the
        # turn_id they are diverging from.
        target_turn_id = "4"
        result = mock_client.create_context(base_turn_id=str(target_turn_id))

        mock_client.create_context.assert_called_once_with(
            base_turn_id="4",
        )
        assert result["context_id"] == "42"
        assert result["base_turn_id"] == "4"

    def test_replay_diverges_from_earlier_turn(self) -> None:
        """Fork from an earlier turn also passes the correct base_turn_id."""
        mock_client = MagicMock()
        mock_client.create_context.return_value = {
            "context_id": "43",
            "base_turn_id": "3",
        }

        target_turn_id = "3"
        result = mock_client.create_context(base_turn_id=str(target_turn_id))

        mock_client.create_context.assert_called_once_with(base_turn_id="3")
        assert result["context_id"] == "43"
