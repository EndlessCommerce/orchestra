from __future__ import annotations

import pytest

from orchestra.engine.graph_analysis import (
    BranchInfo,
    extract_branch_subgraphs,
    find_fan_in_node,
)
from orchestra.models.graph import Edge, Node, PipelineGraph


def _two_branch_graph() -> PipelineGraph:
    """fan_out -> [A, B] -> fan_in"""
    return PipelineGraph(
        name="two_branch",
        nodes={
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
        },
        edges=[
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
        ],
    )


def _four_branch_graph() -> PipelineGraph:
    """fan_out -> [A, B, C, D] -> fan_in"""
    return PipelineGraph(
        name="four_branch",
        nodes={
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "C": Node(id="C", shape="box"),
            "D": Node(id="D", shape="box"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
        },
        edges=[
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="fan_out", to_node="C"),
            Edge(from_node="fan_out", to_node="D"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="C", to_node="fan_in"),
            Edge(from_node="D", to_node="fan_in"),
        ],
    )


def _chain_branch_graph() -> PipelineGraph:
    """fan_out -> [A->B->fan_in, C->fan_in]"""
    return PipelineGraph(
        name="chain_branch",
        nodes={
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "C": Node(id="C", shape="box"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
        },
        edges=[
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="C"),
            Edge(from_node="A", to_node="B"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="C", to_node="fan_in"),
        ],
    )


def _no_fan_in_graph() -> PipelineGraph:
    """fan_out -> [A, B] with no tripleoctagon"""
    return PipelineGraph(
        name="no_fan_in",
        nodes={
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="exit"),
            Edge(from_node="B", to_node="exit"),
        ],
    )


def _divergent_graph() -> PipelineGraph:
    """fan_out -> [A->fan_in, B->exit] — B doesn't converge to fan_in"""
    return PipelineGraph(
        name="divergent",
        nodes={
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="exit"),
        ],
    )


# --- find_fan_in_node tests ---


def test_find_fan_in_two_branches() -> None:
    graph = _two_branch_graph()
    result = find_fan_in_node(graph, "fan_out")
    assert result == "fan_in"


def test_find_fan_in_four_branches() -> None:
    graph = _four_branch_graph()
    result = find_fan_in_node(graph, "fan_out")
    assert result == "fan_in"


def test_find_fan_in_chain_branch() -> None:
    graph = _chain_branch_graph()
    result = find_fan_in_node(graph, "fan_out")
    assert result == "fan_in"


def test_find_fan_in_no_fan_in() -> None:
    graph = _no_fan_in_graph()
    result = find_fan_in_node(graph, "fan_out")
    assert result is None


def test_find_fan_in_divergent_returns_none() -> None:
    graph = _divergent_graph()
    result = find_fan_in_node(graph, "fan_out")
    assert result is None


# --- extract_branch_subgraphs tests ---


def test_extract_two_branch_subgraphs() -> None:
    graph = _two_branch_graph()
    branches = extract_branch_subgraphs(graph, "fan_out", "fan_in")
    assert set(branches.keys()) == {"A", "B"}

    for branch_id, info in branches.items():
        assert info.branch_id == branch_id
        assert info.first_node_id == branch_id
        assert info.subgraph.get_start_node() is not None
        assert len(info.subgraph.get_exit_nodes()) == 1
        assert branch_id in info.subgraph.nodes


def test_extract_four_branch_subgraphs() -> None:
    graph = _four_branch_graph()
    branches = extract_branch_subgraphs(graph, "fan_out", "fan_in")
    assert set(branches.keys()) == {"A", "B", "C", "D"}


def test_extract_chain_branch_subgraph() -> None:
    graph = _chain_branch_graph()
    branches = extract_branch_subgraphs(graph, "fan_out", "fan_in")
    assert set(branches.keys()) == {"A", "C"}

    # Branch A should contain A and B
    a_nodes = set(branches["A"].subgraph.nodes.keys())
    assert "A" in a_nodes
    assert "B" in a_nodes

    # Branch C should contain only C
    c_nodes = set(branches["C"].subgraph.nodes.keys())
    assert "C" in c_nodes
    assert "B" not in c_nodes


def test_extract_divergent_raises() -> None:
    graph = _divergent_graph()
    with pytest.raises(ValueError, match="does not reach fan-in"):
        extract_branch_subgraphs(graph, "fan_out", "fan_in")


def test_extract_no_outgoing_raises() -> None:
    graph = PipelineGraph(
        name="empty",
        nodes={"fan_out": Node(id="fan_out", shape="component")},
        edges=[],
    )
    with pytest.raises(ValueError, match="has no outgoing edges"):
        extract_branch_subgraphs(graph, "fan_out", "fan_in")


def test_subgraph_has_synthetic_start_and_exit() -> None:
    graph = _two_branch_graph()
    branches = extract_branch_subgraphs(graph, "fan_out", "fan_in")
    for info in branches.values():
        start = info.subgraph.get_start_node()
        assert start is not None
        assert start.id.startswith("_start_")
        exits = info.subgraph.get_exit_nodes()
        assert len(exits) == 1
        assert exits[0].id.startswith("_exit_")
