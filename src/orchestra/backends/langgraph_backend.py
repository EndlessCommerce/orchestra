from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from orchestra.backends.errors import sanitize_error
from orchestra.backends.tool_adapter import to_langchain_tool
from orchestra.backends.write_tracker import WriteTracker
from orchestra.models.agent_turn import AgentTurn
from orchestra.models.outcome import Outcome, OutcomeStatus

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from orchestra.backends.protocol import OnTurnCallback
    from orchestra.models.context import Context
    from orchestra.models.graph import Node
    from orchestra.tools.registry import Tool


class LangGraphBackend:
    def __init__(
        self,
        chat_model: BaseChatModel,
        tools: list[Tool] | None = None,
    ) -> None:
        self._chat_model = chat_model
        self._tools = tools or []
        self._write_tracker = WriteTracker()
        self._conversation_messages: list[Any] = []

    def run(
        self,
        node: Node,
        prompt: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        lc_tools = [to_langchain_tool(t) for t in self._tools]

        try:
            agent = create_react_agent(self._chat_model, lc_tools)
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(f"Failed to create agent: {e}"),
            )

        messages = [HumanMessage(content=prompt)]

        try:
            result = agent.invoke({"messages": messages})
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )

        all_messages = result.get("messages", [])

        turn_number = 0
        for msg in all_messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                turn_number += 1
                tool_calls = [
                    {"name": tc.get("name", ""), "args": tc.get("args", {})}
                    for tc in msg.tool_calls
                ]
                files_written = self._write_tracker.flush()

                agent_turn = AgentTurn(
                    turn_number=turn_number,
                    model=getattr(self._chat_model, "model_name", ""),
                    provider="",
                    messages=[{"role": "assistant", "content": str(msg.content)}],
                    tool_calls=tool_calls,
                    files_written=files_written,
                    token_usage=_extract_token_usage(msg),
                    agent_state={},
                )
                if on_turn is not None:
                    on_turn(agent_turn)

        final_message = all_messages[-1] if all_messages else None
        if final_message is not None:
            return str(final_message.content)
        return ""

    def send_message(
        self,
        node: Node,
        message: str,
        context: Context,
        on_turn: OnTurnCallback | None = None,
    ) -> str | Outcome:
        self._conversation_messages.append(HumanMessage(content=message))

        lc_tools = [to_langchain_tool(t) for t in self._tools]
        try:
            agent = create_react_agent(self._chat_model, lc_tools)
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(f"Failed to create agent: {e}"),
            )

        try:
            result = agent.invoke({"messages": list(self._conversation_messages)})
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )

        all_messages = result.get("messages", [])
        # Store full message history for next turn
        self._conversation_messages = list(all_messages)

        final_message = all_messages[-1] if all_messages else None
        if final_message is not None:
            return str(final_message.content)
        return ""

    def reset_conversation(self) -> None:
        self._conversation_messages = []


def _extract_token_usage(msg: Any) -> dict[str, int]:
    usage = getattr(msg, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        return {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
        }
    return {}
