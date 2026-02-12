from __future__ import annotations

from orchestra.backends.simulation import SimulationBackend
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.models.outcome import OutcomeStatus


class SimulationCodergenHandler(CodergenHandler):
    """Backward-compatible wrapper that creates a CodergenHandler with SimulationBackend."""

    def __init__(
        self,
        outcome_sequences: dict[str, list[OutcomeStatus]] | None = None,
    ) -> None:
        backend = SimulationBackend(outcome_sequences=outcome_sequences)
        super().__init__(backend=backend)
