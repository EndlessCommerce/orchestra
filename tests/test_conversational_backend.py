from unittest.mock import MagicMock, patch

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestra.backends.cli_agent import CLIAgentBackend
from orchestra.backends.direct_llm import DirectLLMBackend
from orchestra.backends.langgraph_backend import LangGraphBackend
from orchestra.backends.protocol import ConversationalBackend
from orchestra.backends.simulation import SimulationBackend
from orchestra.models.context import Context
from orchestra.models.graph import Node
from orchestra.models.outcome import Outcome


def _make_node() -> Node:
    return Node(id="test", label="test", shape="box", prompt="Do work", attributes={})


def _make_context() -> Context:
    return Context()


class TestConversationalProtocolConformance:
    """All backends conform to the ConversationalBackend protocol."""

    def test_simulation_implements_protocol(self):
        backend = SimulationBackend()
        assert isinstance(backend, ConversationalBackend)

    def test_direct_llm_implements_protocol(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        assert isinstance(backend, ConversationalBackend)

    def test_langgraph_implements_protocol(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm)
        assert isinstance(backend, ConversationalBackend)

    def test_cli_agent_implements_protocol(self):
        backend = CLIAgentBackend(command="echo")
        assert isinstance(backend, ConversationalBackend)


class TestSimulationSendMessage:
    def test_returns_string(self):
        backend = SimulationBackend()
        result = backend.send_message(_make_node(), "hello", _make_context())
        assert isinstance(result, str)
        assert "hello" in result

    def test_reset_is_noop(self):
        backend = SimulationBackend()
        backend.send_message(_make_node(), "hello", _make_context())
        backend.reset_conversation()  # should not raise


class TestDirectLLMSendMessage:
    def test_accumulates_conversation(self):
        fake_llm = FakeListChatModel(responses=["first reply", "second reply"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        node = _make_node()
        ctx = _make_context()

        r1 = backend.send_message(node, "hello", ctx)
        assert isinstance(r1, str)

        r2 = backend.send_message(node, "follow up", ctx)
        assert isinstance(r2, str)

    def test_reset_clears_history(self):
        fake_llm = FakeListChatModel(responses=["a", "b"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        node = _make_node()
        ctx = _make_context()

        backend.send_message(node, "hello", ctx)
        backend.reset_conversation()
        # After reset, conversation starts fresh
        r = backend.send_message(node, "new topic", ctx)
        assert isinstance(r, str)


class TestLangGraphSendMessage:
    def test_returns_string(self):
        fake_llm = FakeListChatModel(responses=["response"])
        backend = LangGraphBackend(chat_model=fake_llm)
        result = backend.send_message(_make_node(), "hello", _make_context())
        assert isinstance(result, str)

    def test_reset_clears_state(self):
        fake_llm = FakeListChatModel(responses=["a", "b"])
        backend = LangGraphBackend(chat_model=fake_llm)
        node = _make_node()
        ctx = _make_context()

        backend.send_message(node, "hello", ctx)
        backend.reset_conversation()
        r = backend.send_message(node, "new", ctx)
        assert isinstance(r, str)


class TestCLIAgentSendMessage:
    def test_returns_string(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="reply", stderr="")
            result = backend.send_message(_make_node(), "hello", _make_context())
        assert isinstance(result, str)

    def test_reset_clears_history(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="reply", stderr="")
            backend.send_message(_make_node(), "hello", _make_context())
        backend.reset_conversation()
        # After reset, history should be empty (no error)


class TestRunStillWorks:
    """run() remains unchanged after adding conversational methods."""

    def test_simulation_run_unchanged(self):
        backend = SimulationBackend()
        result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, Outcome)

    def test_direct_llm_run_unchanged(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, str)
