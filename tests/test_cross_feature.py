"""Cross-feature integration tests exercising composition of multiple Orchestra features."""
from __future__ import annotations

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
from orchestra.interviewer.models import Answer, AnswerValue, Option
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.handlers.wait_human import WaitHumanHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


class TestConditionalRetryGoalGate:
    """Scenario 1: Conditional + retry + goal gate."""

    def test_branching_with_retry_and_goal_gate(self):
        """Pipeline with conditional branching, retries on failure, and goal gate enforcement."""
        graph = PipelineGraph(
            name="conditional_retry_gate",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "classify": Node(id="classify", shape="box", prompt="Classify input"),
                "gate": Node(id="gate", shape="diamond", label="Route"),
                "fast_path": Node(id="fast_path", shape="box", prompt="Fast process", attributes={"goal_gate": "true"}),
                "slow_path": Node(id="slow_path", shape="box", prompt="Slow process", attributes={"max_retries": "2"}),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="classify"),
                Edge(from_node="classify", to_node="gate"),
                Edge(from_node="gate", to_node="fast_path", condition="context.category=simple"),
                Edge(from_node="gate", to_node="slow_path", condition="context.category=complex"),
                Edge(from_node="fast_path", to_node="exit"),
                Edge(from_node="slow_path", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        class ClassifyHandler:
            def __init__(self) -> None:
                self._delegate = SimulationCodergenHandler()

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                outcome = self._delegate.handle(node, context, graph)
                if node.id == "classify":
                    outcome.context_updates["category"] = "simple"
                return outcome

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("diamond", ConditionalHandler())
        registry.register("box", ClassifyHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify fast_path was taken
        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "fast_path" in completed
        assert "slow_path" not in completed

    def test_retry_on_failure_path(self):
        """When a node fails, retries kick in before routing to failure."""
        graph = PipelineGraph(
            name="retry_test",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "flaky": Node(id="flaky", shape="box", prompt="Flaky task", attributes={"max_retries": "2"}),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="flaky"),
                Edge(from_node="flaky", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        handler = SimulationCodergenHandler(
            outcome_sequences={"flaky": [OutcomeStatus.FAIL, OutcomeStatus.FAIL, OutcomeStatus.SUCCESS]}
        )
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", handler)

        runner = PipelineRunner(graph, registry, emitter, sleep_fn=lambda x: None)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify retry events
        retrying = [e for e in emitter.events if e[0] == "StageRetrying"]
        assert len(retrying) == 2


class TestParallelHumanGate:
    """Scenario 2: Parallel + human gate."""

    def test_parallel_branches_then_human_gate(self):
        """Parallel branches → fan-in → human gate → routing."""
        graph = PipelineGraph(
            name="parallel_human_gate",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "fan_out": Node(id="fan_out", shape="component"),
                "worker_a": Node(id="worker_a", shape="box", prompt="Task A"),
                "worker_b": Node(id="worker_b", shape="box", prompt="Task B"),
                "fan_in": Node(id="fan_in", shape="tripleoctagon"),
                "approval": Node(id="approval", shape="hexagon", label="Approve?"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="fan_out"),
                Edge(from_node="fan_out", to_node="worker_a"),
                Edge(from_node="fan_out", to_node="worker_b"),
                Edge(from_node="worker_a", to_node="fan_in"),
                Edge(from_node="worker_b", to_node="fan_in"),
                Edge(from_node="fan_in", to_node="approval"),
                Edge(from_node="approval", to_node="exit", label="[A] Approve"),
            ],
        )

        emitter = RecordingEmitter()

        # Auto-approve (first option)
        interviewer = QueueInterviewer([
            Answer(value="a", selected_option=Option(key="a", label="Approve"), text="Approve"),
        ])

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", SimulationCodergenHandler())
        registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
        registry.register("tripleoctagon", FanInHandler())
        registry.register("hexagon", WaitHumanHandler(interviewer))

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify parallel branches ran
        branch_completed = [e for e in emitter.events if e[0] == "ParallelBranchCompleted"]
        assert len(branch_completed) == 2

        # Verify human gate was reached
        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "approval" in completed


class TestParallelResume:
    """Scenario 3: Parallel + resume."""

    def test_parallel_with_pause_and_resume(self):
        """Parallel agents → pause → resume → fan-in completes."""
        graph = PipelineGraph(
            name="parallel_resume",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "fan_out": Node(id="fan_out", shape="component"),
                "worker_a": Node(id="worker_a", shape="box", prompt="A"),
                "worker_b": Node(id="worker_b", shape="box", prompt="B"),
                "fan_in": Node(id="fan_in", shape="tripleoctagon"),
                "final": Node(id="final", shape="box", prompt="Final"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="fan_out"),
                Edge(from_node="fan_out", to_node="worker_a"),
                Edge(from_node="fan_out", to_node="worker_b"),
                Edge(from_node="worker_a", to_node="fan_in"),
                Edge(from_node="worker_b", to_node="fan_in"),
                Edge(from_node="fan_in", to_node="final"),
                Edge(from_node="final", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        class PauseAfterFanIn:
            def __init__(self) -> None:
                self._delegate = SimulationCodergenHandler()
                self.runner: PipelineRunner | None = None

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                result = self._delegate.handle(node, context, graph)
                if node.id == "final" and self.runner is not None:
                    self.runner.request_pause()
                    self.runner = None
                return result

        pause_handler = PauseAfterFanIn()
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", pause_handler)
        registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
        registry.register("tripleoctagon", FanInHandler())

        runner = PipelineRunner(graph, registry, emitter)
        pause_handler.runner = runner

        outcome = runner.run()
        assert "PipelinePaused" in [e[0] for e in emitter.events]

        # Extract checkpoint
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        last_cp = checkpoints[-1][1]

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

        # Resume
        resume_emitter = RecordingEmitter()
        resume_registry = HandlerRegistry()
        resume_registry.register("Mdiamond", StartHandler())
        resume_registry.register("Msquare", ExitHandler())
        resume_registry.register("box", SimulationCodergenHandler())
        resume_registry.register("component", ParallelHandler(handler_registry=resume_registry, event_emitter=resume_emitter))
        resume_registry.register("tripleoctagon", FanInHandler())

        resume_runner = PipelineRunner(graph, resume_registry, resume_emitter)
        resume_outcome = resume_runner.resume(state=state, next_node=next_node)

        assert resume_outcome.status == OutcomeStatus.SUCCESS


class TestAgentConfigToolsStylesheet:
    """Scenario 4: Agent config + stylesheet + tools."""

    def test_agent_with_tool_node_and_stylesheet(self):
        """Pipeline with tool handler, box agents, and model stylesheet."""
        graph = PipelineGraph(
            name="agent_tools_stylesheet",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "fetch": Node(id="fetch", shape="parallelogram", attributes={"tool_command": "echo 'data loaded'"}),
                "analyze": Node(id="analyze", shape="box", prompt="Analyze {{ tool.output }}"),
                "report": Node(id="report", shape="box", prompt="Report findings"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="fetch"),
                Edge(from_node="fetch", to_node="analyze"),
                Edge(from_node="analyze", to_node="report"),
                Edge(from_node="report", to_node="exit"),
            ],
            graph_attributes={
                "goal": "Analyze data",
                "model_stylesheet": "* { llm_model: worker; } #report { llm_model: smart; }",
            },
        )

        emitter = RecordingEmitter()
        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("parallelogram", ToolHandler())
        registry.register("box", SimulationCodergenHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify tool.output propagated
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        fetch_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "fetch"]
        assert len(fetch_cp) > 0
        assert fetch_cp[0][1]["context_snapshot"]["tool.output"] == "data loaded"

        # Verify all three nodes executed
        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "fetch" in completed
        assert "analyze" in completed
        assert "report" in completed


class TestFullLargePipeline:
    """Scenario 5: Full 10+ node pipeline with mixed node types."""

    def test_large_mixed_pipeline(self):
        """Large pipeline with tool, parallel, conditional, and standard nodes."""
        graph = PipelineGraph(
            name="large_pipeline",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "setup": Node(id="setup", shape="parallelogram", attributes={"tool_command": "echo 'initialized'"}),
                "validate": Node(id="validate", shape="box", prompt="Validate"),
                "route": Node(id="route", shape="diamond", label="Route"),
                "fan_out": Node(id="fan_out", shape="component"),
                "task_a": Node(id="task_a", shape="box", prompt="Task A"),
                "task_b": Node(id="task_b", shape="box", prompt="Task B"),
                "task_c": Node(id="task_c", shape="box", prompt="Task C"),
                "fan_in": Node(id="fan_in", shape="tripleoctagon"),
                "aggregate": Node(id="aggregate", shape="box", prompt="Aggregate"),
                "finalize": Node(id="finalize", shape="box", prompt="Finalize"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[
                Edge(from_node="start", to_node="setup"),
                Edge(from_node="setup", to_node="validate"),
                Edge(from_node="validate", to_node="route"),
                Edge(from_node="route", to_node="fan_out", condition="context.ready=true"),
                Edge(from_node="fan_out", to_node="task_a"),
                Edge(from_node="fan_out", to_node="task_b"),
                Edge(from_node="fan_out", to_node="task_c"),
                Edge(from_node="task_a", to_node="fan_in"),
                Edge(from_node="task_b", to_node="fan_in"),
                Edge(from_node="task_c", to_node="fan_in"),
                Edge(from_node="fan_in", to_node="aggregate"),
                Edge(from_node="aggregate", to_node="finalize"),
                Edge(from_node="finalize", to_node="exit"),
            ],
        )

        emitter = RecordingEmitter()

        class ValidateHandler:
            def __init__(self) -> None:
                self._delegate = SimulationCodergenHandler()

            def handle(self, node: Node, context: Context, graph: PipelineGraph) -> Outcome:
                outcome = self._delegate.handle(node, context, graph)
                if node.id == "validate":
                    outcome.context_updates["ready"] = "true"
                return outcome

        registry = HandlerRegistry()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("diamond", ConditionalHandler())
        registry.register("parallelogram", ToolHandler())
        registry.register("box", ValidateHandler())
        registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
        registry.register("tripleoctagon", FanInHandler())

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify all nodes executed (12 nodes total including start/exit)
        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "setup" in completed
        assert "validate" in completed
        assert "route" in completed
        assert "aggregate" in completed
        assert "finalize" in completed

        # Verify parallel branches
        branch_completed = [e for e in emitter.events if e[0] == "ParallelBranchCompleted"]
        assert len(branch_completed) == 3

        # Verify checkpoints
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        assert len(checkpoints) >= 8
