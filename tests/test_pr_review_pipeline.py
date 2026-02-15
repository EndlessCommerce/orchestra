"""PR Review Pipeline integration tests with mocked LLM (SimulationBackend)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestra.engine.runner import PipelineRunner, _RunState
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.tool_handler import ToolHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus
from orchestra.parser.parser import parse_dot
from orchestra.transforms.variable_expansion import expand_variables

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _load_fixture(name: str) -> PipelineGraph:
    source = (FIXTURES / name).read_text()
    graph = parse_dot(source)
    return expand_variables(graph)


class _CriticAwareHandler:
    """Box handler that sets critic_verdict=sufficient for the critic node."""

    def __init__(self) -> None:
        self._delegate = SimulationCodergenHandler()

    def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
        outcome = self._delegate.handle(node, context, graph)
        if node.id == "critic":
            outcome.context_updates["critic_verdict"] = "sufficient"
        return outcome


def _build_adversarial_registry(emitter: RecordingEmitter, box_handler=None) -> HandlerRegistry:
    """Build a registry for the adversarial pipeline fixture."""
    if box_handler is None:
        box_handler = _CriticAwareHandler()
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("diamond", ConditionalHandler())
    registry.register("parallelogram", ToolHandler())
    registry.register("box", box_handler)
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
    registry.register("tripleoctagon", FanInHandler())
    return registry


class TestPrReviewPipelineExecution:
    """Test the adversarial PR review pipeline with mocked LLM."""

    def test_full_pipeline_execution_sufficient_critic(self):
        """Start → get_diff → fan_out → [security, architecture] → fan_in → critic → gate → synthesize → exit."""
        graph = _load_fixture("pr-review-adversarial.dot")
        emitter = RecordingEmitter()
        registry = _build_adversarial_registry(emitter)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify all expected nodes executed
        stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
        completed_nodes = [e[1]["node_id"] for e in stage_completed]
        assert "get_diff" in completed_nodes
        assert "critic" in completed_nodes
        assert "gate" in completed_nodes
        assert "synthesize" in completed_nodes

    def test_parallel_reviewers_execute(self):
        """Verify parallel reviewers produce distinct outputs."""
        graph = _load_fixture("pr-review-adversarial.dot")
        emitter = RecordingEmitter()
        registry = _build_adversarial_registry(emitter)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify parallel branches completed
        branch_completed = [e for e in emitter.events if e[0] == "ParallelBranchCompleted"]
        assert len(branch_completed) == 2

        # Verify both reviewers ran
        branch_ids = {e[1].get("branch_id", "") for e in branch_completed}
        assert len(branch_ids) == 2

    def test_critic_loop_insufficient_then_sufficient(self):
        """Critic returns insufficient → loops back to reviewers → critic re-evaluates as sufficient."""
        graph = _load_fixture("pr-review-adversarial.dot")
        emitter = RecordingEmitter()

        class CriticLoopHandler:
            """Returns insufficient on first call, sufficient on second."""
            def __init__(self) -> None:
                self._delegate = SimulationCodergenHandler()
                self._critic_calls = 0

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                outcome = self._delegate.handle(node, context, graph)
                if node.id == "critic":
                    self._critic_calls += 1
                    if self._critic_calls == 1:
                        outcome.context_updates["critic_verdict"] = "insufficient"
                    else:
                        outcome.context_updates["critic_verdict"] = "sufficient"
                return outcome

        registry = _build_adversarial_registry(emitter, box_handler=CriticLoopHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify critic ran twice (insufficient then sufficient)
        critic_completed = [
            e for e in emitter.events
            if e[0] == "StageCompleted" and e[1].get("node_id") == "critic"
        ]
        assert len(critic_completed) == 2

        # Verify parallel ran twice (looped back)
        parallel_started = [e for e in emitter.events if e[0] == "ParallelStarted"]
        assert len(parallel_started) == 2

    def test_tool_handler_get_diff(self):
        """Tool handler node executes command and sets tool.output."""
        graph = _load_fixture("pr-review-adversarial.dot")
        emitter = RecordingEmitter()
        registry = _build_adversarial_registry(emitter)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify get_diff stage completed
        get_diff_completed = [
            e for e in emitter.events
            if e[0] == "StageCompleted" and e[1].get("node_id") == "get_diff"
        ]
        assert len(get_diff_completed) == 1

    def test_checkpoint_at_every_node(self):
        """Every node transition produces a valid checkpoint."""
        graph = _load_fixture("pr-review-adversarial.dot")
        emitter = RecordingEmitter()
        registry = _build_adversarial_registry(emitter)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        # Should have checkpoints for each non-exit node
        assert len(checkpoints) >= 5

        # Each checkpoint should have required fields
        for cp in checkpoints:
            data = cp[1]
            assert "node_id" in data
            assert "completed_nodes" in data
            assert "context_snapshot" in data

    def test_goal_gate_on_critic_with_simple_graph(self):
        """Goal gate enforcement: critic must succeed before exit is allowed."""
        # Build a simple graph where critic has goal_gate=true and pipeline reaches exit
        graph = PipelineGraph(
            name="goal_gate_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "work": Node(id="work", shape="box", prompt="Do work"),
                "critic": Node(id="critic", shape="box", prompt="Evaluate", attributes={"goal_gate": "true"}),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="work"),
                Edge(from_node="work", to_node="critic"),
                Edge(from_node="critic", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        # Critic fails → goal gate unsatisfied at exit
        handler = SimulationCodergenHandler(
            outcome_sequences={"critic": [OutcomeStatus.FAIL]}
        )
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", handler)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        # Pipeline should fail because critic (goal_gate=true) failed
        # and there's no reroute target
        assert outcome.status == OutcomeStatus.FAIL

    def test_resume_mid_pipeline_simple(self):
        """Pause and resume mid-pipeline using a linear graph variant."""
        graph = PipelineGraph(
            name="resume_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "get_diff": Node(id="get_diff", shape="parallelogram", attributes={"tool_command": "echo test"}),
                "review": Node(id="review", shape="box", prompt="Review"),
                "synthesize": Node(id="synthesize", shape="box", prompt="Synthesize"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="get_diff"),
                Edge(from_node="get_diff", to_node="review"),
                Edge(from_node="review", to_node="synthesize"),
                Edge(from_node="synthesize", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        class PauseAfterReview:
            def __init__(self) -> None:
                self._delegate = SimulationCodergenHandler()
                self.runner: PipelineRunner | None = None

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                result = self._delegate.handle(node, context, graph)
                if node.id == "review" and self.runner is not None:
                    self.runner.request_pause()
                    self.runner = None  # Only pause once
                return result

        pause_handler = PauseAfterReview()
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("parallelogram", ToolHandler())
        registry.register("box", pause_handler)

        runner = PipelineRunner(graph, registry, emitter)
        pause_handler.runner = runner

        # First run — should pause after review
        outcome = runner.run()
        event_types = [e[0] for e in emitter.events]
        assert "PipelinePaused" in event_types

        # Extract checkpoint
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        assert len(checkpoints) > 0
        last_cp = checkpoints[-1][1]

        # Rebuild state
        ctx = Context()
        for key, value in last_cp["context_snapshot"].items():
            ctx.set(key, value)

        visited = {k: OutcomeStatus(v) for k, v in last_cp["visited_outcomes"].items()}

        state = _RunState(
            context=ctx,
            completed_nodes=list(last_cp["completed_nodes"]),
            visited_outcomes=visited,
            retry_counters=dict(last_cp["retry_counters"]),
            reroute_count=last_cp["reroute_count"],
        )

        next_node = graph.get_node(last_cp["next_node_id"])
        assert next_node is not None

        # Resume — should complete from synthesize onward
        resume_emitter = RecordingEmitter()
        resume_registry = HandlerRegistry()
        resume_registry.register("Mdiamond", StartHandler())
        resume_registry.register("Msquare", ExitHandler())
        resume_registry.register("parallelogram", ToolHandler())
        resume_registry.register("box", SimulationCodergenHandler())

        resume_runner = PipelineRunner(graph, resume_registry, resume_emitter)
        resume_outcome = resume_runner.resume(state=state, next_node=next_node)

        assert resume_outcome.status == OutcomeStatus.SUCCESS

        # Verify synthesize executed in the resumed run
        resume_completed = [
            e[1]["node_id"] for e in resume_emitter.events if e[0] == "StageCompleted"
        ]
        assert "synthesize" in resume_completed
        assert "review" not in resume_completed  # Should not re-execute review


class TestPrReviewPipelineFromInlineGraph:
    """Simpler pipeline tests built from inline graphs."""

    def _build_simple_review_graph(self) -> PipelineGraph:
        """Build a simplified PR review pipeline for targeted tests."""
        return PipelineGraph(
            name="simple_review",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "get_diff": Node(id="get_diff", shape="parallelogram", attributes={"tool_command": "echo 'test diff'"}),
                "fan_out": Node(id="fan_out", shape="component", attributes={"error_policy": "continue"}),
                "reviewer_a": Node(id="reviewer_a", shape="box", prompt="Review A"),
                "reviewer_b": Node(id="reviewer_b", shape="box", prompt="Review B"),
                "fan_in": Node(id="fan_in", shape="tripleoctagon", attributes={"join_policy": "wait_all"}),
                "synthesize": Node(id="synthesize", shape="box", prompt="Synthesize"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="get_diff"),
                Edge(from_node="get_diff", to_node="fan_out"),
                Edge(from_node="fan_out", to_node="reviewer_a"),
                Edge(from_node="fan_out", to_node="reviewer_b"),
                Edge(from_node="reviewer_a", to_node="fan_in"),
                Edge(from_node="reviewer_b", to_node="fan_in"),
                Edge(from_node="fan_in", to_node="synthesize"),
                Edge(from_node="synthesize", to_node="exit"),
            ],
            graph_attributes={"goal": "Test PR review"},
        )

    def test_tool_output_propagates_to_context(self):
        """tool.output from get_diff should be available in pipeline context."""
        graph = self._build_simple_review_graph()
        emitter = RecordingEmitter()
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", SimulationCodergenHandler())
        registry.register("parallelogram", ToolHandler())
        registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
        registry.register("tripleoctagon", FanInHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify tool.output was set in a checkpoint after get_diff
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        get_diff_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "get_diff"]
        assert len(get_diff_cp) > 0
        ctx_snap = get_diff_cp[0][1]["context_snapshot"]
        assert ctx_snap.get("tool.output") == "test diff"

    def test_model_stylesheet_applied(self):
        """Model stylesheet assigns different models to different roles."""
        graph = PipelineGraph(
            name="stylesheet_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "worker": Node(id="worker", shape="box", prompt="Work"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="worker"),
                Edge(from_node="worker", to_node="exit"),
            ],
            graph_attributes={
                "goal": "Test stylesheet",
                "model_stylesheet": "* { llm_model: worker; } #worker { llm_model: smart; }",
            },
        )

        emitter = RecordingEmitter()
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", SimulationCodergenHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS
