from __future__ import annotations

from orchestra.models.graph import PipelineGraph


def expand_variables(graph: PipelineGraph) -> PipelineGraph:
    goal = graph.goal
    for node in graph.nodes.values():
        if "$goal" in node.prompt:
            node.prompt = node.prompt.replace("$goal", goal)
    return graph
