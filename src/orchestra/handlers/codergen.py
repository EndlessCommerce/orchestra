from __future__ import annotations

from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class SimulationCodergenHandler:
    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        response = f"[Simulated] Response for stage: {node.id}"
        return Outcome(
            status=OutcomeStatus.SUCCESS,
            notes=response,
            context_updates={"last_response": response},
        )
