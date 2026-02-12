from __future__ import annotations

from orchestra.engine.goal_gates import check_goal_gates
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


def test_gate_satisfied_exits_normally() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "critical_work": Node(
                id="critical_work", shape="box",
                attributes={"goal_gate": True},
            ),
        },
    )
    visited = {"critical_work": OutcomeStatus.SUCCESS}

    result = check_goal_gates(visited, graph)
    assert result.satisfied is True


def test_gate_unsatisfied_with_retry_target() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "critical_work": Node(
                id="critical_work", shape="box",
                attributes={"goal_gate": True, "retry_target": "redo"},
            ),
            "redo": Node(id="redo", shape="box"),
        },
    )
    visited = {"critical_work": OutcomeStatus.FAIL}

    result = check_goal_gates(visited, graph)
    assert result.satisfied is False
    assert result.reroute_target == "redo"


def test_gate_unsatisfied_with_graph_level_retry_target() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "critical_work": Node(
                id="critical_work", shape="box",
                attributes={"goal_gate": True},
            ),
            "graph_retry": Node(id="graph_retry", shape="box"),
        },
        graph_attributes={"retry_target": "graph_retry"},
    )
    visited = {"critical_work": OutcomeStatus.FAIL}

    result = check_goal_gates(visited, graph)
    assert result.satisfied is False
    assert result.reroute_target == "graph_retry"


def test_gate_unsatisfied_no_target_pipeline_fails() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "critical_work": Node(
                id="critical_work", shape="box",
                attributes={"goal_gate": True},
            ),
        },
    )
    visited = {"critical_work": OutcomeStatus.FAIL}

    result = check_goal_gates(visited, graph)
    assert result.satisfied is False
    assert result.reroute_target is None


def test_partial_success_satisfies_gate() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "critical_work": Node(
                id="critical_work", shape="box",
                attributes={"goal_gate": True},
            ),
        },
    )
    visited = {"critical_work": OutcomeStatus.PARTIAL_SUCCESS}

    result = check_goal_gates(visited, graph)
    assert result.satisfied is True
