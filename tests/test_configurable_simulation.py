from __future__ import annotations

from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


def _node(node_id: str = "test_node") -> Node:
    return Node(id=node_id, shape="box")


def _graph() -> PipelineGraph:
    return PipelineGraph(name="test")


def test_sequence_fail_fail_success() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"test_node": [OutcomeStatus.FAIL, OutcomeStatus.FAIL, OutcomeStatus.SUCCESS]}
    )
    node = _node()
    ctx = Context()
    graph = _graph()

    assert handler.handle(node, ctx, graph).status == OutcomeStatus.FAIL
    assert handler.handle(node, ctx, graph).status == OutcomeStatus.FAIL
    assert handler.handle(node, ctx, graph).status == OutcomeStatus.SUCCESS


def test_node_without_sequence_returns_success() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"other_node": [OutcomeStatus.FAIL]}
    )
    node = _node("test_node")
    ctx = Context()
    graph = _graph()

    assert handler.handle(node, ctx, graph).status == OutcomeStatus.SUCCESS


def test_exhausted_sequence_returns_last_status() -> None:
    handler = SimulationCodergenHandler(
        outcome_sequences={"test_node": [OutcomeStatus.FAIL, OutcomeStatus.SUCCESS]}
    )
    node = _node()
    ctx = Context()
    graph = _graph()

    assert handler.handle(node, ctx, graph).status == OutcomeStatus.FAIL
    assert handler.handle(node, ctx, graph).status == OutcomeStatus.SUCCESS
    assert handler.handle(node, ctx, graph).status == OutcomeStatus.SUCCESS
    assert handler.handle(node, ctx, graph).status == OutcomeStatus.SUCCESS
