from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestra.backends.cli_agent import CLIAgentBackend
from orchestra.backends.direct_llm import DirectLLMBackend
from orchestra.backends.langgraph_backend import LangGraphBackend
from orchestra.backends.protocol import CodergenBackend
from orchestra.backends.simulation import SimulationBackend
from orchestra.models.context import Context
from orchestra.models.graph import Node
from orchestra.models.outcome import Outcome


def _make_node() -> Node:
    return Node(id="test", label="test", shape="box", prompt="Do work", attributes={})


def _make_context() -> Context:
    return Context()


class TestBackendProtocolConformance:
    """All backends conform to the CodergenBackend protocol."""

    def test_simulation_implements_protocol(self):
        backend = SimulationBackend()
        assert isinstance(backend, CodergenBackend)

    def test_direct_llm_implements_protocol(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        assert isinstance(backend, CodergenBackend)

    def test_langgraph_implements_protocol(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm)
        assert isinstance(backend, CodergenBackend)

    def test_cli_agent_implements_protocol(self):
        backend = CLIAgentBackend(command="echo")
        assert isinstance(backend, CodergenBackend)


class TestBackendAcceptsOnTurnNone:
    """All backends accept on_turn=None without error."""

    def test_simulation_on_turn_none(self):
        backend = SimulationBackend()
        result = backend.run(_make_node(), "prompt", _make_context(), on_turn=None)
        assert isinstance(result, (str, Outcome))

    def test_direct_llm_on_turn_none(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", _make_context(), on_turn=None)
        assert isinstance(result, (str, Outcome))

    def test_langgraph_on_turn_none(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = LangGraphBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", _make_context(), on_turn=None)
        assert isinstance(result, (str, Outcome))

    def test_cli_agent_on_turn_none(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = backend.run(_make_node(), "prompt", _make_context(), on_turn=None)
        assert isinstance(result, (str, Outcome))


class TestBackendReturnTypes:
    """All backends return str or Outcome."""

    def test_simulation_returns_outcome(self):
        backend = SimulationBackend()
        result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, Outcome)

    def test_direct_llm_returns_str(self):
        fake_llm = FakeListChatModel(responses=["response"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, str)

    def test_langgraph_returns_str(self):
        fake_llm = FakeListChatModel(responses=["response"])
        backend = LangGraphBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, str)

    def test_cli_agent_returns_str(self):
        backend = CLIAgentBackend(command="echo")
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            result = backend.run(_make_node(), "prompt", _make_context())
        assert isinstance(result, str)


class TestOnTurnBehavior:
    """DirectLLM and CLI backends ignore on_turn. LangGraph invokes it."""

    def test_direct_llm_ignores_on_turn(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        turns = []
        backend.run(_make_node(), "prompt", _make_context(), on_turn=lambda t: turns.append(t))
        assert turns == []

    def test_cli_agent_ignores_on_turn(self):
        backend = CLIAgentBackend(command="echo")
        turns = []
        with patch("orchestra.backends.cli_agent.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            backend.run(_make_node(), "prompt", _make_context(), on_turn=lambda t: turns.append(t))
        assert turns == []

    def test_simulation_ignores_on_turn(self):
        backend = SimulationBackend()
        turns = []
        backend.run(_make_node(), "prompt", _make_context(), on_turn=lambda t: turns.append(t))
        assert turns == []
