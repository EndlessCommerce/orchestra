from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

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
        self._conversation: list[BaseMessage] = []

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

    def send_message(
        self,
        node: Node,
        message: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        if not self._conversation:
            self._conversation.append(
                SystemMessage(content="You are a helpful assistant.")
            )
        self._conversation.append(HumanMessage(content=message))
        try:
            response = self._chat_model.invoke(self._conversation)
            content = str(response.content)
            self._conversation.append(AIMessage(content=content))
            return content
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )

    def reset_conversation(self) -> None:
        self._conversation = []
