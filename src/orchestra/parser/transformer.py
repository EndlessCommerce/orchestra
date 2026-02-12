from __future__ import annotations

from typing import Any

from lark import Token, Transformer

from orchestra.models.graph import Edge, Node, PipelineGraph


def _parse_value(token: Token) -> Any:
    text = str(token)
    if token.type == "STRING":
        inner = text[1:-1]
        inner = inner.replace('\\"', '"')
        inner = inner.replace("\\n", "\n")
        inner = inner.replace("\\t", "\t")
        inner = inner.replace("\\\\", "\\")
        return inner
    elif token.type == "BOOLEAN":
        return text == "true"
    elif token.type == "FLOAT":
        return float(text)
    elif token.type == "DURATION":
        return text
    elif token.type == "INTEGER":
        return int(text)
    return text


class DotTransformer(Transformer):
    def __init__(self) -> None:
        super().__init__()
        self._graph_name = ""
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._graph_attributes: dict[str, Any] = {}
        self._node_defaults: dict[str, Any] = {}
        self._edge_defaults: dict[str, Any] = {}

    def start(self, items: list) -> PipelineGraph:
        return items[0]

    def graph(self, items: list) -> PipelineGraph:
        self._graph_name = str(items[0])
        for item in items[1:]:
            pass  # statements processed via side effects
        return PipelineGraph(
            name=self._graph_name,
            nodes=self._nodes,
            edges=self._edges,
            graph_attributes=self._graph_attributes,
        )

    def graph_attr_stmt(self, items: list) -> None:
        attrs = items[0]
        self._graph_attributes.update(attrs)

    def graph_attr_decl(self, items: list) -> None:
        key = str(items[0])
        value = items[1]
        self._graph_attributes[key] = value

    def node_defaults(self, items: list) -> None:
        attrs = items[0]
        self._node_defaults.update(attrs)

    def edge_defaults(self, items: list) -> None:
        attrs = items[0]
        self._edge_defaults.update(attrs)

    def subgraph_stmt(self, items: list) -> None:
        saved_node_defaults = dict(self._node_defaults)
        saved_edge_defaults = dict(self._edge_defaults)
        for item in items:
            pass  # statements processed via side effects
        self._node_defaults = saved_node_defaults
        self._edge_defaults = saved_edge_defaults

    def _ensure_node(self, node_id: str, explicit_attrs: dict[str, Any] | None = None) -> None:
        if node_id in self._nodes and explicit_attrs is None:
            return

        merged = dict(self._node_defaults)
        if explicit_attrs:
            merged.update(explicit_attrs)

        shape = merged.pop("shape", "box")
        label = merged.pop("label", node_id)
        prompt = merged.pop("prompt", "")

        self._nodes[node_id] = Node(
            id=node_id,
            label=label,
            shape=shape,
            prompt=prompt,
            attributes=merged,
        )

    def node_stmt(self, items: list) -> None:
        node_id = str(items[0])
        explicit_attrs: dict[str, Any] = {}
        if len(items) > 1 and items[1] is not None:
            explicit_attrs = items[1]
        self._ensure_node(node_id, explicit_attrs)

    def edge_stmt(self, items: list) -> None:
        identifiers = []
        explicit_attrs: dict[str, Any] = {}
        for item in items:
            if isinstance(item, Token) and item.type == "IDENTIFIER":
                identifiers.append(str(item))
            elif isinstance(item, dict):
                explicit_attrs = item

        merged = dict(self._edge_defaults)
        merged.update(explicit_attrs)

        label = merged.pop("label", "")
        condition = merged.pop("condition", "")
        weight = merged.pop("weight", 0)
        if isinstance(weight, str):
            weight = int(weight)

        for i in range(len(identifiers) - 1):
            self._ensure_node(identifiers[i])
            self._ensure_node(identifiers[i + 1])

            edge = Edge(
                from_node=identifiers[i],
                to_node=identifiers[i + 1],
                label=label,
                condition=condition,
                weight=weight,
                attributes=merged,
            )
            self._edges.append(edge)

    def attr_block(self, items: list) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in items:
            if isinstance(item, tuple):
                result[item[0]] = item[1]
        return result

    def attr(self, items: list) -> tuple[str, Any]:
        key = items[0]
        value = items[1]
        return (key, value)

    def key(self, items: list) -> str:
        token = items[0]
        text = str(token)
        if token.type == "STRING":
            return text[1:-1]
        return text

    def value(self, items: list) -> Any:
        token = items[0]
        return _parse_value(token)

    def IDENTIFIER(self, token: Token) -> Token:
        return token
