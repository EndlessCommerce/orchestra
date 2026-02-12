from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from orchestra.models.graph import Edge, Node, PipelineGraph


@dataclass
class BranchInfo:
    branch_id: str
    first_node_id: str
    subgraph: PipelineGraph


def find_fan_in_node(graph: PipelineGraph, fan_out_node_id: str) -> str | None:
    """BFS from each outgoing edge of fan-out, find the first tripleoctagon node reachable from ALL branches."""
    outgoing = graph.get_outgoing_edges(fan_out_node_id)
    if not outgoing:
        return None

    branch_reachable: list[set[str]] = []
    for edge in outgoing:
        reachable: set[str] = set()
        queue: deque[str] = deque([edge.to_node])
        visited: set[str] = set()
        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            node = graph.get_node(nid)
            if node is not None and node.shape == "tripleoctagon":
                reachable.add(nid)
                continue
            for out_edge in graph.get_outgoing_edges(nid):
                queue.append(out_edge.to_node)
        branch_reachable.append(reachable)

    if not branch_reachable:
        return None

    common = branch_reachable[0]
    for s in branch_reachable[1:]:
        common = common & s

    if not common:
        return None

    return min(common)


def extract_branch_subgraphs(
    graph: PipelineGraph,
    fan_out_node_id: str,
    fan_in_node_id: str,
) -> dict[str, BranchInfo]:
    """For each outgoing edge from fan-out: BFS collecting nodes until hitting fan-in, build a PipelineGraph subgraph."""
    outgoing = graph.get_outgoing_edges(fan_out_node_id)
    if not outgoing:
        raise ValueError(f"Fan-out node '{fan_out_node_id}' has no outgoing edges")

    branches: dict[str, BranchInfo] = {}

    for edge in outgoing:
        branch_id = edge.to_node
        first_node_id = edge.to_node

        collected_node_ids: list[str] = []
        collected_edges: list[Edge] = []
        queue: deque[str] = deque([first_node_id])
        visited: set[str] = set()

        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)

            if nid == fan_in_node_id:
                continue

            collected_node_ids.append(nid)
            for out_edge in graph.get_outgoing_edges(nid):
                if out_edge.to_node != fan_in_node_id:
                    collected_edges.append(out_edge)
                queue.append(out_edge.to_node)

        if fan_in_node_id not in visited:
            raise ValueError(
                f"Branch '{branch_id}' does not reach fan-in node '{fan_in_node_id}'"
            )

        start_node = Node(id=f"_start_{branch_id}", shape="Mdiamond", label="start")
        exit_node = Node(id=f"_exit_{branch_id}", shape="Msquare", label="exit")

        nodes: dict[str, Node] = {
            start_node.id: start_node,
            exit_node.id: exit_node,
        }
        for nid in collected_node_ids:
            original = graph.get_node(nid)
            if original is not None:
                nodes[nid] = original

        edges: list[Edge] = [
            Edge(from_node=start_node.id, to_node=first_node_id),
        ]
        edges.extend(collected_edges)

        terminal_ids = set(collected_node_ids) - {
            e.from_node for e in collected_edges
        }
        for tid in terminal_ids:
            edges.append(Edge(from_node=tid, to_node=exit_node.id))

        subgraph = PipelineGraph(
            name=f"branch_{branch_id}",
            nodes=nodes,
            edges=edges,
        )

        branches[branch_id] = BranchInfo(
            branch_id=branch_id,
            first_node_id=first_node_id,
            subgraph=subgraph,
        )

    return branches
