from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.handlers.prompt_helper import compose_node_prompt
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend, OnTurnCallback
    from orchestra.config.settings import OrchestraConfig
    from orchestra.models.context import Context
    from orchestra.models.graph import Node, PipelineGraph


class CodergenHandler:
    def __init__(
        self,
        backend: CodergenBackend,
        config: OrchestraConfig | None = None,
        on_turn: OnTurnCallback | None = None,
    ) -> None:
        self._backend = backend
        self._config = config
        self._on_turn = on_turn

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        prompt = compose_node_prompt(node, context, self._config)

        result = self._backend.run(node, prompt, context, self._on_turn)

        if isinstance(result, str):
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                notes=result,
                context_updates={"last_response": result},
            )
        return result
