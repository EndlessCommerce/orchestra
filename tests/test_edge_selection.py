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


def test_condition_match_wins_over_unconditional() -> None:
    edges = [
        Edge(from_node="a", to_node="b", condition="outcome=success", weight=1),
        Edge(from_node="a", to_node="c", weight=10),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "b"


def test_condition_no_match_falls_through() -> None:
    edges = [
        Edge(from_node="a", to_node="b", condition="outcome=fail", weight=10),
        Edge(from_node="a", to_node="c", weight=1),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "c"


def test_preferred_label_match() -> None:
    edges = [
        Edge(from_node="a", to_node="b", label="Fix"),
        Edge(from_node="a", to_node="c", label="Skip"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS, preferred_label="Fix")
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "b"


def test_label_normalization() -> None:
    edges = [
        Edge(from_node="a", to_node="b", label="[Y] Yes"),
        Edge(from_node="a", to_node="c", label="[N] No"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS, preferred_label="yes")
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "b"


def test_suggested_next_ids() -> None:
    edges = [
        Edge(from_node="a", to_node="b", weight=5),
        Edge(from_node="a", to_node="c", weight=1),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS, suggested_next_ids=["c"])
    context = Context()

    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "c"


def test_full_priority_chain() -> None:
    edges = [
        Edge(from_node="a", to_node="cond_match", condition="outcome=success", weight=0),
        Edge(from_node="a", to_node="label_match", label="Go", weight=0),
        Edge(from_node="a", to_node="suggested", weight=0),
        Edge(from_node="a", to_node="heavy", weight=100),
        Edge(from_node="a", to_node="alpha", weight=0),
    ]
    graph = _branching_graph(edges)

    # Step 1 wins: condition match
    outcome = Outcome(status=OutcomeStatus.SUCCESS, preferred_label="Go", suggested_next_ids=["suggested"])
    context = Context()
    result = select_edge("a", outcome, context, graph)
    assert result is not None
    assert result.to_node == "cond_match"

    # Step 2 wins: condition doesn't match, preferred label does
    outcome2 = Outcome(status=OutcomeStatus.FAIL, preferred_label="Go", suggested_next_ids=["suggested"])
    result2 = select_edge("a", outcome2, context, graph)
    assert result2 is not None
    assert result2.to_node == "label_match"

    # Step 3 wins: no condition match, no label match, suggested ID matches
    outcome3 = Outcome(status=OutcomeStatus.FAIL, suggested_next_ids=["suggested"])
    result3 = select_edge("a", outcome3, context, graph)
    assert result3 is not None
    assert result3.to_node == "suggested"

    # Step 4 wins: no condition, no label, no suggested — highest weight
    outcome4 = Outcome(status=OutcomeStatus.FAIL)
    result4 = select_edge("a", outcome4, context, graph)
    assert result4 is not None
    assert result4.to_node == "heavy"


def test_max_visits_skips_edge_when_target_visited_enough() -> None:
    edges = [
        Edge(
            from_node="gate",
            to_node="fan_out",
            condition="context.critic_verdict=insufficient",
            attributes={"max_visits": 3},
        ),
        Edge(from_node="gate", to_node="synthesize"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()
    context.set("critic_verdict", "insufficient")

    # Under the limit: conditional edge is taken
    context.set("node_visits.fan_out", 2)
    result = select_edge("gate", outcome, context, graph)
    assert result is not None
    assert result.to_node == "fan_out"

    # At the limit: conditional edge skipped, falls through to unconditional
    context.set("node_visits.fan_out", 3)
    result = select_edge("gate", outcome, context, graph)
    assert result is not None
    assert result.to_node == "synthesize"


def test_max_visits_not_checked_when_condition_fails() -> None:
    edges = [
        Edge(
            from_node="gate",
            to_node="fan_out",
            condition="context.critic_verdict=insufficient",
            attributes={"max_visits": 3},
        ),
        Edge(from_node="gate", to_node="synthesize"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()
    context.set("critic_verdict", "sufficient")
    context.set("node_visits.fan_out", 1)

    # Condition doesn't match, so max_visits is irrelevant — fallback is taken
    result = select_edge("gate", outcome, context, graph)
    assert result is not None
    assert result.to_node == "synthesize"


def test_max_visits_zero_blocks_immediately() -> None:
    edges = [
        Edge(
            from_node="a",
            to_node="b",
            condition="outcome=success",
            attributes={"max_visits": 0},
        ),
        Edge(from_node="a", to_node="c"),
    ]
    graph = _branching_graph(edges)
    outcome = Outcome(status=OutcomeStatus.SUCCESS)
    context = Context()

    # Even with no prior visits, max_visits=0 means never take this edge
    # (node_visits.b defaults to 0 which is >= 0)
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
