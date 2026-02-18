from orchestra.backends.simulation import SimulationBackend
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.codergen_handler import CodergenHandler, _extract_context_vars
from orchestra.models.context import Context
from orchestra.models.graph import Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


def _make_node(node_id: str = "test", **attrs) -> Node:
    return Node(id=node_id, label=node_id, shape="box", prompt="Test prompt", attributes=attrs)


def _make_graph() -> PipelineGraph:
    return PipelineGraph(name="test", nodes={}, edges=[], graph_attributes={})


class MockBackend:
    def __init__(self, result: str | Outcome = "mock response"):
        self._result = result
        self.last_prompt: str | None = None

    def run(self, node, prompt, context, on_turn=None):
        self.last_prompt = prompt
        return self._result


class TestCodergenHandler:
    def test_handler_wraps_backend(self):
        backend = MockBackend("hello world")
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.notes == "hello world"

    def test_string_to_outcome_conversion(self):
        backend = MockBackend("response text")
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert isinstance(outcome, Outcome)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.notes == "response text"
        assert outcome.context_updates == {"last_response": "response text"}

    def test_backend_returns_outcome_passthrough(self):
        expected = Outcome(
            status=OutcomeStatus.FAIL,
            failure_reason="API error",
            notes="",
        )
        backend = MockBackend(expected)
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert outcome is expected
        assert outcome.status == OutcomeStatus.FAIL

    def test_passes_node_prompt_to_backend(self):
        backend = MockBackend("ok")
        handler = CodergenHandler(backend=backend)
        node = _make_node()
        handler.handle(node, Context(), _make_graph())
        assert backend.last_prompt == "Test prompt"

    def test_extracts_context_vars_from_response(self):
        response = "Some analysis.\n\n**critic_verdict: insufficient**\n\nMore text."
        backend = MockBackend(response)
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert outcome.context_updates["critic_verdict"] == "insufficient"
        assert outcome.context_updates["last_response"] == response

    def test_extracts_plain_context_var(self):
        response = "Result:\nmy_status: done"
        backend = MockBackend(response)
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert outcome.context_updates["my_status"] == "done"

    def test_no_false_positive_on_uppercase_keys(self):
        response = "File: something.py\nStatus: active"
        backend = MockBackend(response)
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert "File" not in outcome.context_updates
        assert "Status" not in outcome.context_updates


class TestExtractContextVars:
    def test_plain_key_value(self):
        assert _extract_context_vars("critic_verdict: sufficient") == {
            "critic_verdict": "sufficient"
        }

    def test_bold_markdown(self):
        assert _extract_context_vars("**critic_verdict: insufficient**") == {
            "critic_verdict": "insufficient"
        }

    def test_ignores_uppercase_keys(self):
        assert _extract_context_vars("File: foo.py") == {}

    def test_ignores_multi_word_values(self):
        assert _extract_context_vars("key: multiple words here") == {}

    def test_multiple_vars(self):
        text = "verdict: pass\nseverity: high"
        assert _extract_context_vars(text) == {"verdict": "pass", "severity": "high"}

    def test_empty_string(self):
        assert _extract_context_vars("") == {}

    def test_no_match_in_prose(self):
        assert _extract_context_vars("This is a normal sentence: nothing special.") == {}


class TestSimulationBackendCompatibility:
    def test_same_results_as_old_handler(self):
        old_handler = SimulationCodergenHandler()
        new_backend = SimulationBackend()
        new_handler = CodergenHandler(backend=new_backend)

        node = _make_node()
        ctx = Context()
        graph = _make_graph()

        old_outcome = old_handler.handle(node, ctx, graph)
        new_outcome = new_handler.handle(node, ctx, graph)
        assert old_outcome.status == new_outcome.status
        assert old_outcome.notes == new_outcome.notes

    def test_simulation_backend_success(self):
        backend = SimulationBackend()
        handler = CodergenHandler(backend=backend)
        outcome = handler.handle(_make_node(), Context(), _make_graph())
        assert outcome.status == OutcomeStatus.SUCCESS
        assert "[Simulated]" in outcome.notes

    def test_simulation_backend_sequences(self):
        backend = SimulationBackend(
            outcome_sequences={"test": [OutcomeStatus.FAIL, OutcomeStatus.SUCCESS]}
        )
        handler = CodergenHandler(backend=backend)
        node = _make_node()

        outcome1 = handler.handle(node, Context(), _make_graph())
        assert outcome1.status == OutcomeStatus.FAIL

        outcome2 = handler.handle(node, Context(), _make_graph())
        assert outcome2.status == OutcomeStatus.SUCCESS

    def test_simulation_via_backward_compat_wrapper(self):
        handler = SimulationCodergenHandler(
            outcome_sequences={"n": [OutcomeStatus.FAIL]}
        )
        outcome = handler.handle(_make_node("n"), Context(), _make_graph())
        assert outcome.status == OutcomeStatus.FAIL
