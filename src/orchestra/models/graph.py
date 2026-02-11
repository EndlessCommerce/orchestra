from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Node(BaseModel):
    id: str
    label: str = ""
    shape: str = "box"
    prompt: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if not self.label:
            self.label = self.id


class Edge(BaseModel):
    from_node: str
    to_node: str
    label: str = ""
    condition: str = ""
    weight: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)


class PipelineGraph(BaseModel):
    name: str
    nodes: dict[str, Node] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)
    graph_attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def goal(self) -> str:
        return str(self.graph_attributes.get("goal", ""))

    def get_node(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def get_start_node(self) -> Node | None:
        for node in self.nodes.values():
            if node.shape == "Mdiamond":
                return node
        return None

    def get_exit_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.shape == "Msquare"]

    def get_outgoing_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.from_node == node_id]

    def get_incoming_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.to_node == node_id]
