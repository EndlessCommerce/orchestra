from __future__ import annotations

from orchestra.models.context import Context
from orchestra.models.graph import Edge, PipelineGraph
from orchestra.models.outcome import Outcome


def select_edge(
    node_id: str,
    outcome: Outcome,
    context: Context,
    graph: PipelineGraph,
) -> Edge | None:
    edges = graph.get_outgoing_edges(node_id)
    if not edges:
        return None

    # Stage 1: steps 4+5 only (weight + lexical tiebreak among unconditional edges)
    unconditional = [e for e in edges if not e.condition]
    if not unconditional:
        unconditional = edges

    # Sort by weight descending, then by to_node ascending (lexical tiebreak)
    unconditional.sort(key=lambda e: (-e.weight, e.to_node))
    return unconditional[0]
