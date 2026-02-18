from __future__ import annotations

import re
from typing import TYPE_CHECKING

from orchestra.handlers.prompt_helper import compose_node_prompt
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import CodergenBackend, OnTurnCallback
    from orchestra.config.settings import OrchestraConfig
    from orchestra.models.context import Context
    from orchestra.models.graph import Node, PipelineGraph

# Matches lines like "critic_verdict: insufficient" or "**critic_verdict: insufficient**"
# Key must be lowercase snake_case; value must be a single word.
_CONTEXT_VAR_RE = re.compile(r"^([a-z][a-z0-9_]*)\s*:\s*(\w+)$")


def _extract_context_vars(text: str) -> dict[str, str]:
    """Extract key: value context variables from LLM response text."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = line.strip().strip("*_").strip()
        m = _CONTEXT_VAR_RE.match(cleaned)
        if m:
            result[m.group(1)] = m.group(2)
    return result


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
            context_updates = {"last_response": result}
            context_updates.update(_extract_context_vars(result))
            return Outcome(
                status=OutcomeStatus.SUCCESS,
                notes=result,
                context_updates=context_updates,
            )
        return result
