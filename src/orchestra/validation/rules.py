from __future__ import annotations

from collections import deque

from orchestra.models.diagnostics import Diagnostic, Severity
from orchestra.models.graph import PipelineGraph


def start_node(graph: PipelineGraph) -> list[Diagnostic]:
    start_nodes = [n for n in graph.nodes.values() if n.shape == "Mdiamond"]
    if len(start_nodes) == 0:
        return [
            Diagnostic(
                rule="start_node",
                severity=Severity.ERROR,
                message="No start node found (shape=Mdiamond)",
                suggestion="Add a node with shape=Mdiamond to define the pipeline entry point",
            )
        ]
    if len(start_nodes) > 1:
        return [
            Diagnostic(
                rule="start_node",
                severity=Severity.ERROR,
                message=f"Multiple start nodes found: {[n.id for n in start_nodes]}",
                suggestion="A pipeline must have exactly one start node (shape=Mdiamond)",
            )
        ]
    return []


def terminal_node(graph: PipelineGraph) -> list[Diagnostic]:
    exit_nodes = graph.get_exit_nodes()
    if len(exit_nodes) == 0:
        return [
            Diagnostic(
                rule="terminal_node",
                severity=Severity.ERROR,
                message="No exit node found (shape=Msquare)",
                suggestion="Add a node with shape=Msquare to define the pipeline exit point",
            )
        ]
    return []


def reachability(graph: PipelineGraph) -> list[Diagnostic]:
    start = graph.get_start_node()
    if start is None:
        return []

    visited: set[str] = set()
    queue: deque[str] = deque([start.id])
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for edge in graph.get_outgoing_edges(node_id):
            if edge.to_node in graph.nodes:
                queue.append(edge.to_node)

    unreachable = set(graph.nodes.keys()) - visited
    return [
        Diagnostic(
            rule="reachability",
            severity=Severity.ERROR,
            message=f"Node '{nid}' is not reachable from the start node",
            node_id=nid,
            suggestion=f"Add an edge path from the start node to '{nid}', or remove it",
        )
        for nid in sorted(unreachable)
    ]


def edge_target_exists(graph: PipelineGraph) -> list[Diagnostic]:
    diagnostics = []
    for edge in graph.edges:
        if edge.to_node not in graph.nodes:
            diagnostics.append(
                Diagnostic(
                    rule="edge_target_exists",
                    severity=Severity.ERROR,
                    message=f"Edge target '{edge.to_node}' does not exist",
                    edge=(edge.from_node, edge.to_node),
                    suggestion=f"Define node '{edge.to_node}' or fix the edge target",
                )
            )
        if edge.from_node not in graph.nodes:
            diagnostics.append(
                Diagnostic(
                    rule="edge_target_exists",
                    severity=Severity.ERROR,
                    message=f"Edge source '{edge.from_node}' does not exist",
                    edge=(edge.from_node, edge.to_node),
                    suggestion=f"Define node '{edge.from_node}' or fix the edge source",
                )
            )
    return diagnostics


def start_no_incoming(graph: PipelineGraph) -> list[Diagnostic]:
    start = graph.get_start_node()
    if start is None:
        return []
    incoming = graph.get_incoming_edges(start.id)
    if incoming:
        return [
            Diagnostic(
                rule="start_no_incoming",
                severity=Severity.ERROR,
                message=f"Start node '{start.id}' has incoming edges from: {[e.from_node for e in incoming]}",
                node_id=start.id,
                suggestion="Remove edges pointing to the start node",
            )
        ]
    return []


def exit_no_outgoing(graph: PipelineGraph) -> list[Diagnostic]:
    diagnostics = []
    for exit_node in graph.get_exit_nodes():
        outgoing = graph.get_outgoing_edges(exit_node.id)
        if outgoing:
            diagnostics.append(
                Diagnostic(
                    rule="exit_no_outgoing",
                    severity=Severity.ERROR,
                    message=f"Exit node '{exit_node.id}' has outgoing edges to: {[e.to_node for e in outgoing]}",
                    node_id=exit_node.id,
                    suggestion="Remove edges from the exit node",
                )
            )
    return diagnostics


def prompt_on_llm_nodes(graph: PipelineGraph) -> list[Diagnostic]:
    diagnostics = []
    for node in graph.nodes.values():
        if node.shape == "box" and not node.prompt and node.label == node.id:
            diagnostics.append(
                Diagnostic(
                    rule="prompt_on_llm_nodes",
                    severity=Severity.WARNING,
                    message=f"Codergen node '{node.id}' has no prompt or descriptive label",
                    node_id=node.id,
                    suggestion=f"Add a prompt or label attribute to node '{node.id}'",
                )
            )
    return diagnostics


ALL_RULES = [
    start_node,
    terminal_node,
    reachability,
    edge_target_exists,
    start_no_incoming,
    exit_no_outgoing,
    prompt_on_llm_nodes,
]
