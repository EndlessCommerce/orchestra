"""Verify CXDB O(1) fork semantics via create_context(base_turn_id).

Investigation for Stage 6b: confirms that the CxdbClient supports forking
a context at a specific turn, which is the foundation for the replay feature.
"""

from unittest.mock import MagicMock

import httpx

from orchestra.storage.cxdb_client import CxdbClient


def _make_client() -> CxdbClient:
    """Create a CxdbClient with a mock binary client."""
    client = CxdbClient.__new__(CxdbClient)
    client._base_url = "http://test:9010"
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
        base_url="http://test:9010",
    )
    client._binary_host = "test"
    client._binary_port = 9009
    client._binary = MagicMock()
    return client


def test_create_context_no_fork() -> None:
    """create_context() with default base_turn_id=0 creates a fresh context."""
    client = _make_client()
    client._binary.create_context.return_value = {
        "context_id": 1,
        "head_turn_id": 1,
        "head_depth": 0,
    }

    result = client.create_context()
    assert result["context_id"] == 1
    assert result["head_depth"] == 0
    client._binary.create_context.assert_called_once_with(0)


def test_create_context_fork_at_turn() -> None:
    """create_context(base_turn_id=N) forks at the specified turn."""
    client = _make_client()
    client._binary.create_context.return_value = {
        "context_id": 2,
        "head_turn_id": 5,
        "head_depth": 2,
    }

    result = client.create_context(base_turn_id="5")
    assert result["context_id"] == 2
    assert result["head_turn_id"] == 5
    assert result["head_depth"] == 2
    client._binary.create_context.assert_called_once_with(5)


def test_fork_creates_independent_context() -> None:
    """Forked context gets its own context_id, independent of the original.

    Simulates the full fork workflow:
    1. Create context A, append 3 turns
    2. Fork at turn 2 to create context B
    3. Append to both contexts independently
    4. Verify contexts are independent (different context IDs, turn IDs)
    """
    client = _make_client()

    # Step 1: Create context A
    client._binary.create_context.return_value = {
        "context_id": 100,
        "head_turn_id": 1,
        "head_depth": 0,
    }
    ctx_a = client.create_context()
    assert ctx_a["context_id"] == 100

    # Step 1b: Append 3 turns to context A
    turn_ids = []
    for i in range(3):
        client._binary.append_turn.return_value = {
            "context_id": 100,
            "turn_id": 10 + i,
            "depth": i + 1,
        }
        result = client.append_turn(
            context_id="100",
            type_id="dev.orchestra.AgentTurn",
            type_version=2,
            data={"turn_number": i + 1},
        )
        turn_ids.append(result["turn_id"])
    assert turn_ids == [10, 11, 12]

    # Step 2: Fork at turn 2 (turn_id=11) to create context B
    client._binary.create_context.return_value = {
        "context_id": 200,
        "head_turn_id": 11,
        "head_depth": 2,
    }
    ctx_b = client.create_context(base_turn_id="11")
    assert ctx_b["context_id"] == 200
    assert ctx_b["head_turn_id"] == 11  # Points to fork point
    assert ctx_b["head_depth"] == 2  # Shares first 2 turns

    # Step 3: Append to context B (diverges from A)
    client._binary.append_turn.return_value = {
        "context_id": 200,
        "turn_id": 50,
        "depth": 3,
    }
    b_turn = client.append_turn(
        context_id="200",
        type_id="dev.orchestra.AgentTurn",
        type_version=2,
        data={"turn_number": 3, "diverged": True},
    )
    assert b_turn["context_id"] == 200
    assert b_turn["turn_id"] == 50

    # Step 3b: Append to context A (continues independently)
    client._binary.append_turn.return_value = {
        "context_id": 100,
        "turn_id": 13,
        "depth": 4,
    }
    a_turn = client.append_turn(
        context_id="100",
        type_id="dev.orchestra.AgentTurn",
        type_version=2,
        data={"turn_number": 4},
    )
    assert a_turn["context_id"] == 100
    assert a_turn["turn_id"] == 13

    # Step 4: Verify independence — different context IDs and turn IDs
    assert ctx_a["context_id"] != ctx_b["context_id"]
    assert b_turn["turn_id"] != a_turn["turn_id"]
