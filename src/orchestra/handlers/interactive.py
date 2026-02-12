from __future__ import annotations

from typing import TYPE_CHECKING, Any

from orchestra.handlers.prompt_helper import compose_node_prompt
from orchestra.interviewer.models import Answer, AnswerValue, Question, QuestionType
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from orchestra.backends.protocol import ConversationalBackend
    from orchestra.config.settings import OrchestraConfig
    from orchestra.interviewer.base import Interviewer
    from orchestra.models.context import Context
    from orchestra.models.graph import Node, PipelineGraph

_DONE_COMMANDS = {"/done", "/approve"}
_REJECT_COMMANDS = {"/reject"}


class InteractiveHandler:
    def __init__(
        self,
        backend: ConversationalBackend,
        interviewer: Interviewer,
        config: OrchestraConfig | None = None,
    ) -> None:
        self._backend = backend
        self._interviewer = interviewer
        self._config = config

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        prompt = compose_node_prompt(node, context, self._config)
        history: list[dict[str, str]] = list(context.get("interactive.history", []))

        # Resume case: replay prior conversation
        if history:
            self._replay_history(node, context, history)

        # First agent turn
        response = self._backend.send_message(node, prompt, context)
        if isinstance(response, Outcome):
            return response
        agent_text = response

        while True:
            question = Question(
                text=agent_text,
                type=QuestionType.FREEFORM,
                stage=node.id,
            )
            answer = self._interviewer.ask(question)

            human_text = answer.text or str(answer.value)

            # Check commands
            command = human_text.strip().lower()
            if command in _DONE_COMMANDS:
                history.append({"agent": agent_text, "human": human_text})
                break
            if command in _REJECT_COMMANDS:
                history.append({"agent": agent_text, "human": human_text})
                self._backend.reset_conversation()
                return Outcome(
                    status=OutcomeStatus.FAIL,
                    failure_reason="human rejected in interactive mode",
                    notes=self._format_conversation(history),
                    context_updates={"interactive.history": history},
                )

            history.append({"agent": agent_text, "human": human_text})

            # Next agent turn
            response = self._backend.send_message(node, human_text, context)
            if isinstance(response, Outcome):
                self._backend.reset_conversation()
                return response
            agent_text = response

        self._backend.reset_conversation()
        return Outcome(
            status=OutcomeStatus.SUCCESS,
            notes=self._format_conversation(history),
            context_updates={
                "interactive.history": history,
                "last_response": agent_text,
            },
        )

    def _replay_history(
        self,
        node: Node,
        context: Context,
        history: list[dict[str, str]],
    ) -> None:
        for entry in history:
            self._interviewer.inform(
                f"[resumed] Agent: {entry.get('agent', '')}", stage=node.id
            )
            self._interviewer.inform(
                f"[resumed] You: {entry.get('human', '')}", stage=node.id
            )
            # Replay messages to rebuild backend conversation state
            self._backend.send_message(node, entry.get("agent", ""), context)
            human_msg = entry.get("human", "")
            if human_msg:
                self._backend.send_message(node, human_msg, context)

    def _format_conversation(self, history: list[dict[str, str]]) -> str:
        lines = []
        for entry in history:
            lines.append(f"Agent: {entry.get('agent', '')}")
            lines.append(f"Human: {entry.get('human', '')}")
        return "\n".join(lines)
