from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from orchestra.backends.errors import sanitize_error
from orchestra.backends.tool_adapter import to_langchain_tool
from orchestra.backends.write_tracker import WriteTracker
from orchestra.models.agent_turn import AgentTurn
from orchestra.models.outcome import Outcome, OutcomeStatus

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS_CODES = {429, 502, 503, 529}
_MAX_RETRIES = 5
_INITIAL_DELAY = 2.0
_BACKOFF_FACTOR = 2.0
_MAX_DELAY = 60.0

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from orchestra.backends.protocol import OnTurnCallback
    from orchestra.models.context import Context
    from orchestra.models.graph import Node
    from orchestra.tools.registry import Tool


class LangGraphBackend:
    DEFAULT_RECURSION_LIMIT = 1000

    def __init__(
        self,
        chat_model: BaseChatModel,
        tools: list[Tool] | None = None,
        write_tracker: WriteTracker | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        provider_name: str = "",
    ) -> None:
        self._chat_model = chat_model
        self._tools = tools or []
        self._write_tracker = write_tracker or WriteTracker()
        self._recursion_limit = recursion_limit
        self._provider_name = provider_name
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
            all_messages = self._stream_with_retry(agent, messages, on_turn)
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )

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
            all_messages = self._stream_with_retry(
                agent, list(self._conversation_messages), on_turn,
            )
        except Exception as e:
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason=sanitize_error(str(e)),
            )

        self._conversation_messages = list(all_messages)

        final_message = all_messages[-1] if all_messages else None
        if final_message is not None:
            return str(final_message.content)
        return ""

    def _stream_with_retry(
        self,
        agent: Any,
        messages: list,
        on_turn: OnTurnCallback | None = None,
    ) -> list:
        """Stream agent execution with retries for transient API errors."""
        delay = _INITIAL_DELAY
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                return self._stream_agent(agent, messages, on_turn)
            except Exception as e:
                if attempt < _MAX_RETRIES and _is_transient(e):
                    logger.warning(
                        "Transient API error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, _MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)
                    delay = min(delay * _BACKOFF_FACTOR, _MAX_DELAY)
                    continue
                raise
        raise RuntimeError("retry loop exited unexpectedly")

    def _stream_agent(
        self,
        agent: Any,
        messages: list,
        on_turn: OnTurnCallback | None = None,
    ) -> list:
        """Stream agent execution, firing on_turn callbacks as steps complete."""
        turn_number = 0
        all_messages = list(messages)
        config = {"recursion_limit": self._recursion_limit}

        for chunk in agent.stream(
            {"messages": messages},
            config=config,
            stream_mode="updates",
        ):
            # Each chunk is {node_name: {field: value}}
            # The "agent" node produces AI messages; the "tools" node produces tool results
            for node_name, update in chunk.items():
                new_messages = update.get("messages", [])
                all_messages.extend(new_messages)

                for msg in new_messages:
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
                            provider=self._provider_name,
                            messages=[{"role": "assistant", "content": str(msg.content)}],
                            tool_calls=tool_calls,
                            files_written=files_written,
                            token_usage=_extract_token_usage(msg),
                            agent_state={},
                        )
                        if on_turn is not None:
                            on_turn(agent_turn)

        return all_messages

    def reset_conversation(self) -> None:
        self._conversation_messages = []


def _is_transient(exc: Exception) -> bool:
    """Check if an exception is a transient API error worth retrying."""
    status_code = getattr(exc, "status_code", None)
    if status_code in _TRANSIENT_STATUS_CODES:
        return True
    error_str = str(exc)
    for code in _TRANSIENT_STATUS_CODES:
        if f"Error code: {code}" in error_str:
            return True
    if "overloaded" in error_str.lower():
        return True
    return False


def _extract_token_usage(msg: Any) -> dict[str, int]:
    usage = getattr(msg, "usage_metadata", None)
    if usage and isinstance(usage, dict):
        return {
            "input": usage.get("input_tokens", 0),
            "output": usage.get("output_tokens", 0),
        }
    return {}
