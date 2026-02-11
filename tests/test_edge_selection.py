from __future__ import annotations

from orchestra.engine.edge_selection import select_edge
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


def _branching_graph(edges: list[Edge]) -> PipelineGraph:
    node_ids = set()
    for e in edges:
        node_ids.add(e.from_node)
        node_ids.add(e.to_node)
    nodes = {nid: Node(id=nid, shape="box") for nid in node_ids}
    return PipelineGraph(name="test", nodes=nodes, edges=edges)


def test_highest_weight_selected() -> None:
    edges = [
        Edge(from_node="a", to_node="b", weight=1),
        Edge(from_node="a", to_node="c", weight=5),
        Edge(from_node="a", to_node="d", weight=3),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "c"


def test_lexical_tiebreak_on_equal_weights() -> None:
    edges = [
        Edge(from_node="a", to_node="z_last"),
        Edge(from_node="a", to_node="a_first"),
        Edge(from_node="a", to_node="m_middle"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "a_first"


def test_unconditional_preferred_over_conditional() -> None:
    edges = [
        Edge(from_node="a", to_node="b", condition="outcome == success", weight=10),
        Edge(from_node="a", to_node="c", weight=1),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "c"


def test_no_outgoing_edges_returns_none() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={"a": Node(id="a", shape="box")},
        edges=[],
    )
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is None
