from __future__ import annotations

from dataclasses import dataclass

from orchestra.models.graph import PipelineGraph
from orchestra.models.outcome import OutcomeStatus


@dataclass
class GateResult:
    satisfied: bool
    reroute_target: str | None = None


def check_goal_gates(
    visited_outcomes: dict[str, OutcomeStatus],
    graph: PipelineGraph,
) -> GateResult:
    unsatisfied_nodes: list[str] = []

    for node_id, outcome_status in visited_outcomes.items():
        node = graph.get_node(node_id)
        if node is None:
            continue
        if not node.attributes.get("goal_gate"):
            continue
        if outcome_status in (OutcomeStatus.SUCCESS, OutcomeStatus.PARTIAL_SUCCESS):
            continue
        unsatisfied_nodes.append(node_id)

    if not unsatisfied_nodes:
        return GateResult(satisfied=True)

    # Find reroute target from first unsatisfied node or graph-level fallbacks
    for node_id in unsatisfied_nodes:
        node = graph.get_node(node_id)
        if node is None:
            continue
        retry_target = node.attributes.get("retry_target")
        if retry_target and retry_target in graph.nodes:
            return GateResult(satisfied=False, reroute_target=str(retry_target))
        fallback = node.attributes.get("fallback_retry_target")
        if fallback and fallback in graph.nodes:
            return GateResult(satisfied=False, reroute_target=str(fallback))

    # Graph-level fallbacks
    graph_retry = graph.graph_attributes.get("retry_target")
    if graph_retry and graph_retry in graph.nodes:
        return GateResult(satisfied=False, reroute_target=str(graph_retry))
    graph_fallback = graph.graph_attributes.get("fallback_retry_target")
    if graph_fallback and graph_fallback in graph.nodes:
        return GateResult(satisfied=False, reroute_target=str(graph_fallback))

    return GateResult(satisfied=False, reroute_target=None)
