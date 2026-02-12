from langchain_core.language_models.fake_chat_models import FakeListChatModel

from orchestra.backends.direct_llm import DirectLLMBackend
from orchestra.models.context import Context
from orchestra.models.graph import Node
from orchestra.models.outcome import Outcome, OutcomeStatus


def _make_node() -> Node:
    return Node(id="test", label="test", shape="box", prompt="Write a haiku", attributes={})


class TestDirectLLMBackend:
    def test_mock_llm_returns_response(self):
        fake_llm = FakeListChatModel(responses=["A beautiful haiku"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "Write a haiku", Context())
        assert result == "A beautiful haiku"

    def test_returns_string(self):
        fake_llm = FakeListChatModel(responses=["Response text"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, str)

    def test_does_not_invoke_on_turn(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        on_turn_called = []
        backend.run(
            _make_node(),
            "prompt",
            Context(),
            on_turn=lambda turn: on_turn_called.append(turn),
        )
        assert on_turn_called == []

    def test_llm_error_returns_fail_outcome(self):
        class FailingLLM(FakeListChatModel):
            def invoke(self, *args, **kwargs):
                raise RuntimeError("API rate limit exceeded")

        backend = DirectLLMBackend(chat_model=FailingLLM(responses=[]))
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert result.status == OutcomeStatus.FAIL
        assert "rate limit" in result.failure_reason

    def test_error_sanitizes_api_key(self):
        class FailingLLM(FakeListChatModel):
            def invoke(self, *args, **kwargs):
                raise RuntimeError("Auth failed with key sk-abc123xyz")

        backend = DirectLLMBackend(chat_model=FailingLLM(responses=[]))
        result = backend.run(_make_node(), "prompt", Context())
        assert isinstance(result, Outcome)
        assert "sk-abc123xyz" not in result.failure_reason
        assert "[REDACTED]" in result.failure_reason

    def test_accepts_on_turn_none(self):
        fake_llm = FakeListChatModel(responses=["ok"])
        backend = DirectLLMBackend(chat_model=fake_llm)
        result = backend.run(_make_node(), "prompt", Context(), on_turn=None)
        assert result == "ok"
