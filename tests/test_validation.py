from orchestra.models.diagnostics import Severity
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.validation.validator import ValidationError, validate, validate_or_raise

import pytest


def _make_graph(
    nodes: dict[str, Node] | None = None,
    edges: list[Edge] | None = None,
) -> PipelineGraph:
    return PipelineGraph(
        name="test",
        nodes=nodes or {},
        edges=edges or [],
    )


def test_missing_start_node() -> None:
    graph = _make_graph(
        nodes={"a": Node(id="a", shape="box"), "exit": Node(id="exit", shape="Msquare")},
        edges=[Edge(from_node="a", to_node="exit")],
    )
    result = validate(graph)
    assert result.has_errors
    error_rules = [d.rule for d in result.errors]
    assert "start_node" in error_rules


def test_missing_exit_node() -> None:
    graph = _make_graph(
        nodes={"start": Node(id="start", shape="Mdiamond"), "a": Node(id="a", shape="box")},
        edges=[Edge(from_node="start", to_node="a")],
    )
    result = validate(graph)
    assert result.has_errors
    error_rules = [d.rule for d in result.errors]
    assert "terminal_node" in error_rules


def test_start_node_has_incoming_edges() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "a": Node(id="a", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="a"),
            Edge(from_node="a", to_node="start"),
            Edge(from_node="a", to_node="exit"),
        ],
    )
    result = validate(graph)
    assert result.has_errors
    error_rules = [d.rule for d in result.errors]
    assert "start_no_incoming" in error_rules


def test_exit_node_has_outgoing_edges() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "a": Node(id="a", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="a"),
            Edge(from_node="a", to_node="exit"),
            Edge(from_node="exit", to_node="a"),
        ],
    )
    result = validate(graph)
    assert result.has_errors
    error_rules = [d.rule for d in result.errors]
    assert "exit_no_outgoing" in error_rules


def test_unreachable_node() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "a": Node(id="a", shape="box"),
            "orphan": Node(id="orphan", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="a"),
            Edge(from_node="a", to_node="exit"),
        ],
    )
    result = validate(graph)
    assert result.has_errors
    unreachable = [d for d in result.errors if d.rule == "reachability"]
    assert len(unreachable) == 1
    assert unreachable[0].node_id == "orphan"


def test_edge_target_doesnt_exist() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="nonexistent"),
            Edge(from_node="start", to_node="exit"),
        ],
    )
    result = validate(graph)
    assert result.has_errors
    target_errors = [d for d in result.errors if d.rule == "edge_target_exists"]
    assert len(target_errors) >= 1


def test_missing_prompt_on_codergen_node() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "bare": Node(id="bare", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="bare"),
            Edge(from_node="bare", to_node="exit"),
        ],
    )
    result = validate(graph)
    warnings = [d for d in result.warnings if d.rule == "prompt_on_llm_nodes"]
    assert len(warnings) == 1
    assert warnings[0].node_id == "bare"


def test_valid_pipeline_passes() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan it"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
    )
    result = validate(graph)
    assert not result.has_errors


def test_actionable_error_messages() -> None:
    graph = _make_graph(
        nodes={"a": Node(id="a", shape="box")},
        edges=[],
    )
    result = validate(graph)
    assert result.has_errors
    for d in result.errors:
        assert d.rule, "Diagnostic must have a rule name"
        assert d.severity == Severity.ERROR
        assert d.message, "Diagnostic must have a message"
        assert d.suggestion, "Diagnostic must have a suggestion"


def test_validate_or_raise_raises() -> None:
    graph = _make_graph(
        nodes={"a": Node(id="a", shape="box")},
        edges=[],
    )
    with pytest.raises(ValidationError):
        validate_or_raise(graph)


def test_validate_or_raise_passes() -> None:
    graph = _make_graph(
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan it"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
    )
    result = validate_or_raise(graph)
    assert not result.has_errors
