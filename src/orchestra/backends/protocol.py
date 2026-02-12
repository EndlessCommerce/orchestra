from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:
    from orchestra.models.agent_turn import AgentTurn
    from orchestra.models.context import Context
    from orchestra.models.graph import Node
    from orchestra.models.outcome import Outcome

OnTurnCallback = Callable[["AgentTurn"], None]


@runtime_checkable
class CodergenBackend(Protocol):
    def run(
        self,
        node: Node,
        prompt: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome: ...


@runtime_checkable
class ConversationalBackend(Protocol):
    """Extension of CodergenBackend for multi-turn interactive conversations.

    Backends implement send_message() to maintain conversation state across turns,
    and reset_conversation() to clear that state.
    """

    def run(
        self,
        node: Node,
        prompt: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome: ...

    def send_message(
        self,
        node: Node,
        message: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome: ...

    def reset_conversation(self) -> None: ...
