from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend, OnTurnCallback
    from orchestra.config.settings import AgentConfig, OrchestraConfig
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
        prompt = node.prompt

        agent_config = self._get_agent_config(node)
        if agent_config is not None and self._config is not None:
            from orchestra.prompts.engine import compose_prompt

            composed = compose_prompt(
                agent_config,
                context=context.snapshot(),
            )
            if composed:
                prompt = composed

        result = self._backend.run(node, prompt, context, self._on_turn)

        if isinstance(result, str):
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                notes=result,
                context_updates={"last_response": result},
            )
        return result

    def _get_agent_config(self, node: Node) -> AgentConfig | None:
        if self._config is None:
            return None
        agent_name = node.attributes.get("agent", "")
        if agent_name and agent_name in self._config.agents:
            return self._config.agents[agent_name]
        return None
