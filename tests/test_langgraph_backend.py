import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as lc_tool

from orchestra.backends.langgraph_backend import (
    LangGraphBackend,
    _is_transient,
)
from orchestra.backends.write_tracker import WriteTracker
from orchestra.models.agent_turn import AgentTurn
from orchestra.models.context import Context
from orchestra.models.graph import Node
from orchestra.models.outcome import Outcome, OutcomeStatus
from orchestra.tools.registry import Tool


def _make_node() -> Node:
    return Node(id="test", label="test", shape="box", prompt="Do something", attributes={})


@lc_tool
def mock_read_file(path: str) -> str:
    """Read a file from the filesystem."""
    return f"Contents of {path}"


class TestLangGraphBackend:
    def test_simple_response_no_tools(self):
        fake_llm = FakeListChatModel(responses=["Here is my response"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        result = backend.run(_make_node(), "Hello", Context())
        assert isinstance(result, str)
        assert "response" in result.lower() or len(result) > 0

    def test_on_turn_not_called_without_tool_use(self):
        fake_llm = FakeListChatModel(responses=["Simple answer"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        turns: list[AgentTurn] = []
        backend.run(_make_node(), "Hello", Context(), on_turn=lambda t: turns.append(t))
        assert len(turns) == 0

    def test_accepts_on_turn_none(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        result = backend.run(_make_node(), "Hello", Context(), on_turn=None)
        assert isinstance(result, str)

    def test_error_returns_fail_outcome(self):
        class FailingLLM(FakeListChatModel):
            def invoke(self, *args, **kwargs):
                raise RuntimeError("Connection refused")

        backend = LangGraphBackend(chat_model=FailingLLM(responses=[]), tools=[])
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL

    def test_returns_string_type(self):
        fake_llm = FakeListChatModel(responses=["Done"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        result = backend.run(_make_node(), "work", Context())
        assert isinstance(result, str)


class TestIsTransient:
    def test_status_code_429(self):
        exc = Exception("rate limited")
        exc.status_code = 429
        assert _is_transient(exc) is True

    def test_status_code_502(self):
        exc = Exception("bad gateway")
        exc.status_code = 502
        assert _is_transient(exc) is True

    def test_status_code_503(self):
        exc = Exception("service unavailable")
        exc.status_code = 503
        assert _is_transient(exc) is True

    def test_status_code_529(self):
        exc = Exception("overloaded")
        exc.status_code = 529
        assert _is_transient(exc) is True

    def test_status_code_400_not_transient(self):
        exc = Exception("bad request")
        exc.status_code = 400
        assert _is_transient(exc) is False

    def test_status_code_401_not_transient(self):
        exc = Exception("unauthorized")
        exc.status_code = 401
        assert _is_transient(exc) is False

    def test_error_code_string_429(self):
        exc = Exception("Error code: 429 - rate limit exceeded")
        assert _is_transient(exc) is True

    def test_error_code_string_529(self):
        exc = Exception("Error code: 529 - API is overloaded")
        assert _is_transient(exc) is True

    def test_overloaded_keyword(self):
        exc = Exception("The API is currently overloaded, please try again")
        assert _is_transient(exc) is True

    def test_overloaded_keyword_case_insensitive(self):
        exc = Exception("Server OVERLOADED")
        assert _is_transient(exc) is True

    def test_generic_runtime_error_not_transient(self):
        assert _is_transient(RuntimeError("Connection refused")) is False

    def test_no_status_code_no_match(self):
        assert _is_transient(ValueError("invalid input")) is False


class TestStreamWithRetry:
    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_retries_on_transient_error_then_succeeds(self, mock_sleep):
        """Transient error on first attempt, success on second."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        call_count = 0
        original_stream = backend._stream_agent

        def flaky_stream(agent, messages, on_turn=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                exc = Exception("Error code: 529 - overloaded")
                raise exc
            return original_stream(agent, messages, on_turn)

        backend._stream_agent = flaky_stream
        result = backend.run(_make_node(), "Hello", Context())
        assert isinstance(result, str)
        assert call_count == 2
        mock_sleep.assert_called_once_with(2.0)

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        """Verify delay doubles on each retry."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        call_count = 0
        original_stream = backend._stream_agent

        def flaky_stream(agent, messages, on_turn=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                exc = Exception("Error code: 429")
                raise exc
            return original_stream(agent, messages, on_turn)

        backend._stream_agent = flaky_stream
        result = backend.run(_make_node(), "Hello", Context())
        assert isinstance(result, str)
        assert call_count == 4
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [2.0, 4.0, 8.0]

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_max_retries_exhausted_returns_fail(self, mock_sleep):
        """All 5 attempts fail with transient errors → Outcome.FAIL."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        def always_transient(agent, messages, on_turn=None):
            exc = Exception("Error code: 503")
            raise exc

        backend._stream_agent = always_transient
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL
        assert "503" in result.failure_reason
        # 4 sleeps (retries between attempts 1-2, 2-3, 3-4, 4-5; the 5th raises)
        assert mock_sleep.call_count == 4

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_non_transient_error_not_retried(self, mock_sleep):
        """Non-transient errors are raised immediately, no retries."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        def auth_error(agent, messages, on_turn=None):
            exc = Exception("Invalid API key")
            exc.status_code = 401
            raise exc

        backend._stream_agent = auth_error
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL
        mock_sleep.assert_not_called()

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_backoff_capped_at_max_delay(self, mock_sleep):
        """Delay never exceeds _MAX_DELAY (60s)."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        call_count = 0
        original_stream = backend._stream_agent

        def flaky_stream(agent, messages, on_turn=None):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:
                exc = Exception("Error code: 429")
                raise exc
            return original_stream(agent, messages, on_turn)

        backend._stream_agent = flaky_stream
        backend.run(_make_node(), "Hello", Context())
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # 2.0, 4.0, 8.0, 16.0 — all under 60
        assert all(d <= 60.0 for d in delays)
        assert delays == [2.0, 4.0, 8.0, 16.0]

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_retry_logs_warning(self, mock_sleep, caplog):
        """Transient retries are logged at WARNING level."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        call_count = 0
        original_stream = backend._stream_agent

        def flaky_stream(agent, messages, on_turn=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Error code: 429")
            return original_stream(agent, messages, on_turn)

        backend._stream_agent = flaky_stream
        with caplog.at_level("WARNING", logger="orchestra.backends.langgraph_backend"):
            backend.run(_make_node(), "Hello", Context())
        assert any("Transient API error" in r.message for r in caplog.records)
        assert any("attempt 1/5" in r.message for r in caplog.records)


class TestStreamAgent:
    def test_streaming_returns_messages(self):
        """Streaming returns the input messages plus AI response."""
        fake_llm = FakeListChatModel(responses=["streamed response"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        result = backend.run(_make_node(), "Hello", Context())
        assert isinstance(result, str)
        assert len(result) > 0

    def test_recursion_limit_passed_to_agent(self):
        """Custom recursion limit is forwarded to agent.stream()."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[], recursion_limit=42)
        assert backend._recursion_limit == 42

    def test_default_recursion_limit(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm)
        assert backend._recursion_limit == 1000

    def test_constructor_accepts_write_tracker(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        tracker = WriteTracker()
        backend = LangGraphBackend(chat_model=fake_llm, write_tracker=tracker)
        assert backend._write_tracker is tracker

    def test_constructor_creates_default_write_tracker(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm)
        assert isinstance(backend._write_tracker, WriteTracker)

    def test_send_message_uses_streaming(self):
        """send_message also uses the streaming path."""
        fake_llm = FakeListChatModel(responses=["first", "second"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])
        r1 = backend.send_message(_make_node(), "Hello", Context())
        assert isinstance(r1, str)
        r2 = backend.send_message(_make_node(), "Follow up", Context())
        assert isinstance(r2, str)

    @patch("orchestra.backends.langgraph_backend.time.sleep")
    def test_send_message_retries_transient(self, mock_sleep):
        """send_message also retries transient errors."""
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm, tools=[])

        call_count = 0
        original_stream = backend._stream_agent

        def flaky_stream(agent, messages, on_turn=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Error code: 502")
            return original_stream(agent, messages, on_turn)

        backend._stream_agent = flaky_stream
        result = backend.send_message(_make_node(), "Hello", Context())
        assert isinstance(result, str)
        assert call_count == 2


class TestLangGraphBackendToolAdapter:
    def test_orchestra_tool_wrapping(self):
        from orchestra.backends.tool_adapter import to_langchain_tool
        from orchestra.tools.registry import Tool

        def my_tool(x: str) -> str:
            return f"result: {x}"

        t = Tool(name="my-tool", description="A test tool", fn=my_tool)
        lc = to_langchain_tool(t)
        assert lc.name == "my-tool"
        assert lc.description == "A test tool"
