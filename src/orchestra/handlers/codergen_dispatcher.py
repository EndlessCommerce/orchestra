from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestra.handlers.codergen_handler import CodergenHandler
    from orchestra.handlers.interactive import InteractiveHandler
    from orchestra.models.context import Context
    from orchestra.models.graph import Node, PipelineGraph
    from orchestra.models.outcome import Outcome


class CodergenDispatcher:
    def __init__(
        self,
        standard: CodergenHandler,
        interactive: InteractiveHandler,
    ) -> None:
        self._standard = standard
        self._interactive = interactive

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        if node.attributes.get("agent.mode") == "interactive":
            return self._interactive.handle(node, context, graph)
        return self._standard.handle(node, context, graph)
