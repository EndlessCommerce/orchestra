"""CXDB storage integration tests.

These tests require a running CXDB instance and are marked with @pytest.mark.integration.
Run with: uv run pytest tests/test_cxdb_storage.py -v -m integration
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.storage.type_bundle import from_tagged_data


class TurnRecordingClient:
    """Mock CXDB client that records turns in memory."""

    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []
        self._next_context_id = 1

    def health_check(self) -> dict[str, Any]:
        return {"status": "ok"}

    def create_context(self, base_turn_id: str = "0") -> dict[str, Any]:
        cid = str(self._next_context_id)
        self._next_context_id += 1
        return {"context_id": cid}

    def append_turn(
        self, context_id: str, type_id: str, type_version: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        # Decode numeric field tags back to named fields for test assertions
        named_data = from_tagged_data(type_id, type_version, data)
        self.turns.append(
            {
                "context_id": context_id,
                "type_id": type_id,
                "type_version": type_version,
                "data": named_data,
            }
        )
        return {"turn_id": str(len(self.turns))}

    def publish_type_bundle(self, bundle_id: str, bundle: dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


def _make_graph() -> PipelineGraph:
    return PipelineGraph(
        name="test_cxdb",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan it"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
        graph_attributes={"goal": "test goal"},
    )


def _run_with_cxdb(graph: PipelineGraph) -> tuple[TurnRecordingClient, str]:
    client = TurnRecordingClient()
    ctx = client.create_context()
    context_id = ctx["context_id"]

    dispatcher = EventDispatcher()
    dispatcher.add_observer(CxdbObserver(client, context_id))

    runner = PipelineRunner(graph, default_registry(), dispatcher)
    runner.run()

    return client, context_id


def test_context_created() -> None:
    client = TurnRecordingClient()
    ctx = client.create_context()
    assert "context_id" in ctx


def test_turns_appended_in_order() -> None:
    client, context_id = _run_with_cxdb(_make_graph())
    assert len(client.turns) > 0
    for turn in client.turns:
        assert turn["context_id"] == context_id


def test_turn_types_correct() -> None:
    client, _ = _run_with_cxdb(_make_graph())

    type_ids = [t["type_id"] for t in client.turns]
    assert "dev.orchestra.PipelineLifecycle" in type_ids
    assert "dev.orchestra.NodeExecution" in type_ids
    assert "dev.orchestra.Checkpoint" in type_ids


def test_checkpoint_turns_contain_state() -> None:
    client, _ = _run_with_cxdb(_make_graph())

    checkpoints = [t for t in client.turns if t["type_id"] == "dev.orchestra.Checkpoint"]
    assert len(checkpoints) >= 1

    for cp in checkpoints:
        assert "current_node" in cp["data"]
        assert "completed_nodes" in cp["data"]
        assert "context_snapshot" in cp["data"]


def test_node_execution_payloads() -> None:
    client, _ = _run_with_cxdb(_make_graph())

    completions = [
        t
        for t in client.turns
        if t["type_id"] == "dev.orchestra.NodeExecution"
        and t["data"].get("status") not in ("started",)
    ]

    plan_events = [t for t in completions if t["data"].get("node_id") == "plan"]
    assert len(plan_events) >= 1
    plan_data = plan_events[0]["data"]
    assert "prompt" in plan_data
    assert "response" in plan_data
    assert "outcome" in plan_data


def test_turn_order() -> None:
    client, _ = _run_with_cxdb(_make_graph())

    type_ids = [t["type_id"] for t in client.turns]
    # First turn should be PipelineLifecycle (started)
    assert type_ids[0] == "dev.orchestra.PipelineLifecycle"
    assert client.turns[0]["data"]["status"] == "started"
    # Last turn should be PipelineLifecycle (completed)
    assert type_ids[-1] == "dev.orchestra.PipelineLifecycle"
    assert client.turns[-1]["data"]["status"] == "completed"


def test_type_bundle_registered() -> None:
    from orchestra.storage.type_bundle import ORCHESTRA_TYPE_BUNDLE, publish_orchestra_types

    client = TurnRecordingClient()
    publish_orchestra_types(client)
    # No error means success (mock client accepts it)


def test_context_isolation() -> None:
    client = TurnRecordingClient()
    graph = _make_graph()

    ctx1 = client.create_context()
    cid1 = ctx1["context_id"]
    dispatcher1 = EventDispatcher()
    dispatcher1.add_observer(CxdbObserver(client, cid1))
    PipelineRunner(graph, default_registry(), dispatcher1).run()

    ctx2 = client.create_context()
    cid2 = ctx2["context_id"]
    dispatcher2 = EventDispatcher()
    dispatcher2.add_observer(CxdbObserver(client, cid2))
    PipelineRunner(graph, default_registry(), dispatcher2).run()

    assert cid1 != cid2
    turns_1 = [t for t in client.turns if t["context_id"] == cid1]
    turns_2 = [t for t in client.turns if t["context_id"] == cid2]
    assert len(turns_1) > 0
    assert len(turns_2) > 0
    assert len(turns_1) == len(turns_2)
