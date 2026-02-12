from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

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
            error_msg = _sanitize_error(str(e))
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=error_msg,
            )


def _sanitize_error(error: str) -> str:
    error = re.sub(r"(sk-|key-)[a-zA-Z0-9_-]+", "[REDACTED]", error)
    error = re.sub(r"Bearer\s+[a-zA-Z0-9_-]+", "Bearer [REDACTED]", error)
    return error
