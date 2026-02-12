from __future__ import annotations

from orchestra.engine.failure_routing import resolve_failure_target
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


def _fail_outcome() -> Outcome:
    return Outcome(status=OutcomeStatus.FAIL, failure_reason="test failure")


def test_fail_edge_followed() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "work": Node(id="work", shape="box"),
            "recovery": Node(id="recovery", shape="box"),
        },
        edges=[
            Edge(from_node="work", to_node="recovery", condition="outcome=fail"),
        ],
    )
    node = graph.nodes["work"]
    outcome = _fail_outcome()
    context = Context()

    target = resolve_failure_target(node, graph, outcome, context)
    assert target == "recovery"


def test_retry_target_used_when_no_fail_edge() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "work": Node(id="work", shape="box", attributes={"retry_target": "retry_node"}),
            "retry_node": Node(id="retry_node", shape="box"),
        },
        edges=[],
    )
    node = graph.nodes["work"]
    outcome = _fail_outcome()
    context = Context()

    target = resolve_failure_target(node, graph, outcome, context)
    assert target == "retry_node"


def test_fallback_retry_target_used_when_no_retry_target() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "work": Node(id="work", shape="box", attributes={"fallback_retry_target": "fallback_node"}),
            "fallback_node": Node(id="fallback_node", shape="box"),
        },
        edges=[],
    )
    node = graph.nodes["work"]
    outcome = _fail_outcome()
    context = Context()

    target = resolve_failure_target(node, graph, outcome, context)
    assert target == "fallback_node"


def test_pipeline_termination_when_no_failure_route() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "work": Node(id="work", shape="box"),
        },
        edges=[],
    )
    node = graph.nodes["work"]
    outcome = _fail_outcome()
    context = Context()

    target = resolve_failure_target(node, graph, outcome, context)
    assert target is None
