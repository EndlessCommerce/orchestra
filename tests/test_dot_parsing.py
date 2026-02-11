from pathlib import Path

import pytest

from orchestra.parser.parser import DotParseError, parse_dot

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_linear_pipeline() -> None:
    source = (FIXTURES / "test-linear.dot").read_text()
    graph = parse_dot(source)

    assert graph.name == "test_linear"
    assert len(graph.nodes) == 5
    assert len(graph.edges) == 4

    assert graph.get_start_node() is not None
    assert graph.get_start_node().id == "start"
    assert len(graph.get_exit_nodes()) == 1
    assert graph.get_exit_nodes()[0].id == "exit"

    edge_pairs = [(e.from_node, e.to_node) for e in graph.edges]
    assert ("start", "plan") in edge_pairs
    assert ("plan", "build") in edge_pairs
    assert ("build", "review") in edge_pairs
    assert ("review", "exit") in edge_pairs


def test_parse_graph_level_attributes() -> None:
    source = (FIXTURES / "test-graph-attributes.dot").read_text()
    graph = parse_dot(source)

    assert graph.goal == "build the widget"
    assert graph.graph_attributes["label"] == "My Pipeline"
    assert graph.graph_attributes["model_stylesheet"] == "node { model: gpt-4 }"
    assert graph.graph_attributes["rankdir"] == "LR"


def test_parse_node_attributes() -> None:
    source = (FIXTURES / "test-all-value-types.dot").read_text()
    graph = parse_dot(source)

    node_a = graph.get_node("a")
    assert node_a is not None
    assert node_a.shape == "box"
    assert node_a.label == "Test"
    assert node_a.prompt == "hello\nworld"
    assert node_a.attributes["max_retries"] == 3
    assert node_a.attributes["goal_gate"] is True
    assert node_a.attributes["timeout"] == "900s"


def test_parse_edge_attributes() -> None:
    source = (FIXTURES / "test-all-value-types.dot").read_text()
    graph = parse_dot(source)

    edges_to_exit = [e for e in graph.edges if e.to_node == "exit"]
    assert len(edges_to_exit) == 1
    assert edges_to_exit[0].weight == 5


def test_parse_chained_edges() -> None:
    source = (FIXTURES / "test-chained-edges.dot").read_text()
    graph = parse_dot(source)

    chained = [e for e in graph.edges if e.label == "chain"]
    assert len(chained) == 3
    chain_pairs = [(e.from_node, e.to_node) for e in chained]
    assert ("A", "B") in chain_pairs
    assert ("B", "C") in chain_pairs
    assert ("start", "A") in chain_pairs


def test_parse_node_edge_defaults() -> None:
    source = (FIXTURES / "test-node-edge-defaults.dot").read_text()
    graph = parse_dot(source)

    node_a = graph.get_node("a")
    assert node_a is not None
    assert node_a.shape == "box"
    assert node_a.attributes["timeout"] == "900s"

    # Start overrides the default shape
    assert graph.get_node("start").shape == "Mdiamond"

    # Edge defaults apply
    for edge in graph.edges:
        assert edge.weight == 0


def test_parse_subgraphs() -> None:
    source = (FIXTURES / "test-subgraph.dot").read_text()
    graph = parse_dot(source)

    # Subgraph contents flattened
    assert "plan" in graph.nodes
    assert "implement" in graph.nodes

    # Node defaults scoped to subgraph
    plan = graph.get_node("plan")
    assert plan.attributes.get("timeout") == "900s"

    # Explicit override within subgraph
    implement = graph.get_node("implement")
    assert implement.attributes.get("timeout") == "1800s"


def test_parse_comments() -> None:
    source = (FIXTURES / "test-comments.dot").read_text()
    graph = parse_dot(source)

    assert graph.name == "test_comments"
    assert graph.goal == "comments test"
    assert len(graph.nodes) == 3


def test_parse_all_value_types() -> None:
    source = (FIXTURES / "test-all-value-types.dot").read_text()
    graph = parse_dot(source)

    # String
    assert graph.goal == "test values"
    # Integer
    assert graph.graph_attributes["default_max_retry"] == 50
    # Boolean
    node_a = graph.get_node("a")
    assert node_a.attributes["goal_gate"] is True
    # Duration
    assert node_a.attributes["timeout"] == "900s"
    # Integer on node
    assert node_a.attributes["max_retries"] == 3


def test_reject_undirected_graph() -> None:
    source = (FIXTURES / "test-undirected.dot").read_text()
    with pytest.raises(DotParseError, match="[Uu]ndirected"):
        parse_dot(source)


def test_reject_multiple_graphs() -> None:
    source = (FIXTURES / "test-multiple-graphs.dot").read_text()
    with pytest.raises(DotParseError, match="[Mm]ultiple"):
        parse_dot(source)
