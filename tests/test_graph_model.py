from __future__ import annotations

from orchestra.models.graph import Edge, Node, PipelineGraph


def _sample_graph() -> PipelineGraph:
    return PipelineGraph(
        name="test",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "a": Node(id="a", shape="box"),
            "b": Node(id="b", shape="box"),
            "exit1": Node(id="exit1", shape="Msquare"),
            "exit2": Node(id="exit2", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="a"),
            Edge(from_node="start", to_node="b"),
            Edge(from_node="a", to_node="exit1"),
            Edge(from_node="b", to_node="exit1"),
            Edge(from_node="b", to_node="exit2"),
        ],
    )


def test_get_incoming_edges() -> None:
    graph = _sample_graph()
    incoming = graph.get_incoming_edges("exit1")
    assert len(incoming) == 2
    sources = {e.from_node for e in incoming}
    assert sources == {"a", "b"}


def test_get_incoming_edges_none() -> None:
    graph = _sample_graph()
    incoming = graph.get_incoming_edges("start")
    assert len(incoming) == 0


def test_get_exit_nodes() -> None:
    graph = _sample_graph()
    exits = graph.get_exit_nodes()
    assert len(exits) == 2
    exit_ids = {n.id for n in exits}
    assert exit_ids == {"exit1", "exit2"}
