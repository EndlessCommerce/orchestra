import json

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool as lc_tool

from orchestra.backends.langgraph_backend import LangGraphBackend
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
