from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from orchestra.backends.errors import sanitize_error
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from orchestra.backends.protocol import OnTurnCallback
    from orchestra.models.context import Context
    from orchestra.models.graph import Node


class DirectLLMBackend:
    def __init__(self, chat_model: BaseChatModel) -> None:
        self._chat_model = chat_model

    def run(
        self,
        node: Node,
        prompt: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content=prompt),
        ]
        try:
            response = self._chat_model.invoke(messages)
            content = str(response.content)
            return content
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )
