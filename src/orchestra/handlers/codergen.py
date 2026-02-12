from __future__ import annotations

from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class SimulationCodergenHandler:
    def __init__(
        self,
        outcome_sequences: dict[str, list[OutcomeStatus]] | None = None,
    ) -> None:
        self._sequences = outcome_sequences or {}
        self._call_counts: dict[str, int] = {}

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        response = f"[Simulated] Response for stage: {node.id}"
        status = self._resolve_status(node.id)
        failure_reason = f"Simulated failure for {node.id}" if status == OutcomeStatus.FAIL else ""
        return Outcome(
            status=status,
            notes=response,
            context_updates={"last_response": response},
            failure_reason=failure_reason,
        )

    def _resolve_status(self, node_id: str) -> OutcomeStatus:
        if node_id not in self._sequences:
            return OutcomeStatus.SUCCESS

        sequence = self._sequences[node_id]
        call_index = self._call_counts.get(node_id, 0)
        self._call_counts[node_id] = call_index + 1

        if call_index < len(sequence):
            return sequence[call_index]
        return sequence[-1]
