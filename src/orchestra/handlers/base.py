from __future__ import annotations

from typing import Protocol

from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome


class NodeHandler(Protocol):
    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome: ...
