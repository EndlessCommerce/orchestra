"""Tests for graceful pause (SIGINT) functionality."""
from __future__ import annotations

from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _linear_graph_3() -> PipelineGraph:
    return PipelineGraph(
        name="test_3node",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan it"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
    )


def _linear_graph_5() -> PipelineGraph:
    return PipelineGraph(
        name="test_5node",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan it"),
            "build": Node(id="build", shape="box", label="Build", prompt="Build it"),
            "review": Node(id="review", shape="box", label="Review", prompt="Review it"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="build"),
            Edge(from_node="build", to_node="review"),
            Edge(from_node="review", to_node="exit"),
        ],
    )


def _registry() -> HandlerRegistry:
    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())
    reg.register("box", SimulationCodergenHandler())
    return reg


def test_graceful_pause() -> None:
    """SIGINT during execution completes current node, saves checkpoint, and exits cleanly."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()

    # Use a handler that triggers pause after plan node
    class PauseAfterPlanHandler:
        def __init__(self, runner_ref: PipelineRunner) -> None:
            self._runner = runner_ref
            self._delegate = SimulationCodergenHandler()

        def handle(self, node, context, graph):
            result = self._delegate.handle(node, context, graph)
            if node.id == "plan":
                self._runner.request_pause()
            return result

    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())

    runner = PipelineRunner(graph, _registry(), emitter)
    pause_handler = PauseAfterPlanHandler(runner)
    reg.register("box", pause_handler)

    # Need to create runner with the pause-aware registry
    runner = PipelineRunner(graph, reg, emitter)
    pause_handler._runner = runner

    outcome = runner.run()

    # Pipeline should have stopped with pause
    assert outcome.failure_reason == "Pipeline paused by user"

    # PipelinePaused event should have been emitted
    event_types = [e[0] for e in emitter.events]
    assert "PipelinePaused" in event_types
    assert "PipelineCompleted" not in event_types

    # A checkpoint should have been saved at the pause point
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    assert len(checkpoints) >= 2  # start + plan

    # The last checkpoint should be for plan (the node that triggered pause)
    last_cp = checkpoints[-1][1]
    assert last_cp["node_id"] == "plan"
    assert last_cp["next_node_id"] == "build"

    # Verify the pause event has the correct checkpoint_node_id
    pause_event = [e for e in emitter.events if e[0] == "PipelinePaused"][0]
    assert pause_event[1]["checkpoint_node_id"] == "plan"


def test_pause_saves_complete_checkpoint() -> None:
    """Checkpoint saved during pause contains all state needed for resume."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()

    class PauseAfterBuildHandler:
        def __init__(self, runner_ref: PipelineRunner) -> None:
            self._runner = runner_ref
            self._delegate = SimulationCodergenHandler()

        def handle(self, node, context, graph):
            result = self._delegate.handle(node, context, graph)
            if node.id == "build":
                self._runner.request_pause()
            return result

    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())

    runner = PipelineRunner(graph, reg, emitter)
    pause_handler = PauseAfterBuildHandler(runner)
    reg.register("box", pause_handler)

    runner = PipelineRunner(graph, reg, emitter)
    pause_handler._runner = runner
    runner.run()

    # Get the build checkpoint
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    build_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "build"][0][1]

    # Verify all resume fields are present
    assert build_cp["completed_nodes"] == ["start", "plan", "build"]
    assert build_cp["next_node_id"] == "review"
    assert "context_snapshot" in build_cp
    assert "retry_counters" in build_cp
    assert "visited_outcomes" in build_cp
    assert "reroute_count" in build_cp

    # Verify context snapshot has expected keys
    snapshot = build_cp["context_snapshot"]
    assert snapshot["last_stage"] == "build"


def test_pause_and_resume_end_to_end() -> None:
    """Full pause-and-resume cycle: pause after plan, resume completes."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()

    class PauseAfterStartHandler:
        def __init__(self, runner_ref: PipelineRunner) -> None:
            self._runner = runner_ref
            self._delegate = SimulationCodergenHandler()

        def handle(self, node, context, graph):
            result = self._delegate.handle(node, context, graph)
            if node.id == "start":
                self._runner.request_pause()
            return result

    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())

    runner = PipelineRunner(graph, reg, emitter)
    pause_handler = PauseAfterStartHandler(runner)
    reg.register("box", pause_handler)

    runner = PipelineRunner(graph, reg, emitter)
    pause_handler._runner = runner
    runner.run()

    # Get start checkpoint
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    start_cp = checkpoints[0][1]
    assert start_cp["node_id"] == "start"
    assert start_cp["next_node_id"] == "plan"

    # Build resume state from checkpoint
    from orchestra.models.context import Context
    from orchestra.engine.runner import _RunState

    ctx = Context()
    for key, value in start_cp["context_snapshot"].items():
        ctx.set(key, value)
    visited = {k: OutcomeStatus(v) for k, v in start_cp["visited_outcomes"].items()}
    state = _RunState(
        context=ctx,
        completed_nodes=list(start_cp["completed_nodes"]),
        visited_outcomes=visited,
        retry_counters=dict(start_cp["retry_counters"]),
        reroute_count=start_cp["reroute_count"],
    )

    # Resume
    resume_emitter = RecordingEmitter()
    resume_runner = PipelineRunner(graph, _registry(), resume_emitter)
    next_node = graph.get_node("plan")
    assert next_node is not None

    outcome = resume_runner.resume(state=state, next_node=next_node)
    assert outcome.status == OutcomeStatus.SUCCESS

    # All remaining nodes should have executed
    stage_started = [e for e in resume_emitter.events if e[0] == "StageStarted"]
    started_nodes = [e[1]["node_id"] for e in stage_started]
    assert "plan" in started_nodes
    assert "build" in started_nodes
    assert "review" in started_nodes
    assert "start" not in started_nodes


def test_request_pause_sets_flag() -> None:
    """request_pause() sets the pause flag on the runner."""
    graph = _linear_graph_3()
    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, _registry(), emitter)

    assert runner._pause_requested is False
    runner.request_pause()
    assert runner._pause_requested is True
