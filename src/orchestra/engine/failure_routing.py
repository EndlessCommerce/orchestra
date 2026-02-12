from __future__ import annotations

from orchestra.conditions.evaluator import evaluate_condition
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome


def resolve_failure_target(
    node: Node,
    graph: PipelineGraph,
    outcome: Outcome,
    context: Context,
) -> str | None:
    # Step 1: Outgoing edge with condition="outcome=fail"
    for edge in graph.get_outgoing_edges(node.id):
        if edge.condition and evaluate_condition(edge.condition, outcome, context):
            return edge.to_node

    # Step 2: Node attribute retry_target
    retry_target = node.attributes.get("retry_target")
    if retry_target and retry_target in graph.nodes:
        return str(retry_target)

    # Step 3: Node attribute fallback_retry_target
    fallback = node.attributes.get("fallback_retry_target")
    if fallback and fallback in graph.nodes:
        return str(fallback)

    # Step 4: No failure route — pipeline terminates
    return None
