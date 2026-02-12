from __future__ import annotations

from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class ConditionalHandler:
    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        return Outcome(status=OutcomeStatus.SUCCESS)
