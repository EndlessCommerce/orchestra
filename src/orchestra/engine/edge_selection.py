from __future__ import annotations

from orchestra.conditions.evaluator import ConditionParseError, evaluate_condition
from orchestra.interviewer.accelerator import parse_accelerator
from orchestra.models.context import Context
from orchestra.models.graph import Edge, PipelineGraph
from orchestra.models.outcome import Outcome


def _normalize_label(label: str) -> str:
    _key, clean_label = parse_accelerator(label)
    return clean_label.strip().lower()


def select_edge(
    node_id: str,
    outcome: Outcome,
    context: Context,
    graph: PipelineGraph,
) -> Edge | None:
    edges = graph.get_outgoing_edges(node_id)
    if not edges:
        return None

    # Step 1: Condition match — first edge whose condition evaluates to true
    conditional = [e for e in edges if e.condition]
    for edge in conditional:
        try:
            if evaluate_condition(edge.condition, outcome, context):
                # Honour max_visits: skip this edge if the target node has
                # already been visited the maximum number of times.
                max_visits = edge.attributes.get("max_visits")
                if max_visits is not None:
                    target_visits = context.get(f"node_visits.{edge.to_node}", 0)
                    if isinstance(target_visits, int) and target_visits >= int(max_visits):
                        continue
                return edge
        except ConditionParseError:
            continue

    # Step 2: Preferred label match
    if outcome.preferred_label:
        preferred = outcome.preferred_label.strip().lower()
        for edge in edges:
            if edge.label and _normalize_label(edge.label) == preferred:
                return edge

    # Step 3: Suggested next IDs
    if outcome.suggested_next_ids:
        target_set = set(outcome.suggested_next_ids)
        for edge in edges:
            if edge.to_node in target_set:
                return edge

    # Step 4+5: Highest weight among unconditional edges, lexical tiebreak
    unconditional = [e for e in edges if not e.condition]
    if not unconditional:
        unconditional = edges

    unconditional.sort(key=lambda e: (-e.weight, e.to_node))
    return unconditional[0]
