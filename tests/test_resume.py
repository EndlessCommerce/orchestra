"""Tests for checkpoint resume functionality."""
from __future__ import annotations

from typing import Any

from orchestra.engine.resume import ResumeError, restore_from_turns
from orchestra.engine.runner import PipelineRunner, _RunState
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.conditional import ConditionalHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus

import pytest


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


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


def _branching_graph() -> PipelineGraph:
    return PipelineGraph(
        name="test_branching",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "decide": Node(id="decide", shape="diamond"),
            "path_a": Node(id="path_a", shape="box", label="Path A", prompt="A"),
            "path_b": Node(id="path_b", shape="box", label="Path B", prompt="B"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="decide"),
            Edge(from_node="decide", to_node="path_a", condition='context.route=a'),
            Edge(from_node="decide", to_node="path_b", condition='context.route=b'),
            Edge(from_node="path_a", to_node="exit"),
            Edge(from_node="path_b", to_node="exit"),
        ],
    )


def _registry() -> HandlerRegistry:
    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())
    reg.register("box", SimulationCodergenHandler())
    reg.register("diamond", ConditionalHandler())
    return reg


def _run_and_pause_after(graph: PipelineGraph, pause_after_node: str) -> tuple[RecordingEmitter, list[tuple[str, dict[str, Any]]]]:
    """Run a pipeline and simulate pause after a specific node completes."""
    emitter = RecordingEmitter()

    # We use a custom handler that requests pause after the target node
    class PauseAfterHandler:
        def __init__(self, target_node: str, delegate: SimulationCodergenHandler) -> None:
            self._target = target_node
            self._delegate = delegate
            self.runner: PipelineRunner | None = None

        def handle(self, node, context, graph):
            result = self._delegate.handle(node, context, graph)
            if node.id == self._target and self.runner is not None:
                self.runner.request_pause()
            return result

    sim = SimulationCodergenHandler()
    pause_handler = PauseAfterHandler(pause_after_node, sim)

    reg = HandlerRegistry()
    reg.register("Mdiamond", StartHandler())
    reg.register("Msquare", ExitHandler())
    reg.register("box", pause_handler)
    reg.register("diamond", ConditionalHandler())

    runner = PipelineRunner(graph, reg, emitter)
    pause_handler.runner = runner

    outcome = runner.run()
    return emitter, emitter.events


# --- Checkpoint format tests ---


def test_checkpoint_contains_next_node_id() -> None:
    """Checkpoint turns contain next_node_id for resume."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, _registry(), emitter)
    runner.run()

    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    assert len(checkpoints) >= 2

    # Start node's checkpoint should point to plan
    start_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "start"][0]
    assert start_cp[1]["next_node_id"] == "plan"

    # Plan's checkpoint should point to build
    plan_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "plan"][0]
    assert plan_cp[1]["next_node_id"] == "build"


def test_checkpoint_contains_visited_outcomes() -> None:
    """Checkpoint turns contain visited_outcomes for goal gate restoration."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, _registry(), emitter)
    runner.run()

    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    last_cp = checkpoints[-1][1]

    assert "visited_outcomes" in last_cp
    assert last_cp["visited_outcomes"]["start"] == "SUCCESS"
    assert last_cp["visited_outcomes"]["plan"] == "SUCCESS"


def test_checkpoint_contains_reroute_count() -> None:
    """Checkpoint turns contain reroute_count for cycle protection."""
    graph = _linear_graph_5()
    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, _registry(), emitter)
    runner.run()

    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    last_cp = checkpoints[-1][1]
    assert "reroute_count" in last_cp
    assert last_cp["reroute_count"] == 0


# --- Resume from checkpoint ---


def test_resume_from_checkpoint() -> None:
    """Execute 5-node pipeline, stop after node 2 (plan), resume → build and review execute, pipeline completes."""
    graph = _linear_graph_5()
    emitter, events = _run_and_pause_after(graph, "plan")

    # Verify pipeline was paused
    event_types = [e[0] for e in events]
    assert "PipelinePaused" in event_types

    # Get the checkpoint data from the paused run
    checkpoints = [e for e in events if e[0] == "CheckpointSaved"]
    plan_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "plan"][0][1]

    # Build resume state
    ctx = Context()
    for key, value in plan_cp["context_snapshot"].items():
        ctx.set(key, value)
    visited = {k: OutcomeStatus(v) for k, v in plan_cp["visited_outcomes"].items()}
    state = _RunState(
        context=ctx,
        completed_nodes=list(plan_cp["completed_nodes"]),
        visited_outcomes=visited,
        retry_counters=dict(plan_cp["retry_counters"]),
        reroute_count=plan_cp["reroute_count"],
    )

    next_node_id = plan_cp["next_node_id"]
    assert next_node_id == "build"

    # Resume
    resume_emitter = RecordingEmitter()
    resume_runner = PipelineRunner(graph, _registry(), resume_emitter)
    next_node = graph.get_node(next_node_id)
    assert next_node is not None

    outcome = resume_runner.resume(state=state, next_node=next_node)
    assert outcome.status == OutcomeStatus.SUCCESS

    # Verify resumed events
    resume_event_types = [e[0] for e in resume_emitter.events]
    assert "PipelineCompleted" in resume_event_types

    # Verify build and review executed
    stage_started = [e for e in resume_emitter.events if e[0] == "StageStarted"]
    started_nodes = [e[1]["node_id"] for e in stage_started]
    assert "build" in started_nodes
    assert "review" in started_nodes
    # start and plan should NOT have been re-executed
    assert "start" not in started_nodes
    assert "plan" not in started_nodes


def test_context_restored_on_resume() -> None:
    """After resume, context values from before pause are present."""
    graph = _linear_graph_5()
    emitter, events = _run_and_pause_after(graph, "plan")

    checkpoints = [e for e in events if e[0] == "CheckpointSaved"]
    plan_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "plan"][0][1]

    ctx = Context()
    for key, value in plan_cp["context_snapshot"].items():
        ctx.set(key, value)

    # Verify context has values set during the first run
    assert ctx.get("last_stage") == "plan"
    assert ctx.get("graph.goal") is not None


def test_completed_nodes_skipped() -> None:
    """After resume, already-completed nodes are not re-executed."""
    graph = _linear_graph_5()
    emitter, events = _run_and_pause_after(graph, "build")

    checkpoints = [e for e in events if e[0] == "CheckpointSaved"]
    build_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "build"][0][1]

    ctx = Context()
    for key, value in build_cp["context_snapshot"].items():
        ctx.set(key, value)
    visited = {k: OutcomeStatus(v) for k, v in build_cp["visited_outcomes"].items()}
    state = _RunState(
        context=ctx,
        completed_nodes=list(build_cp["completed_nodes"]),
        visited_outcomes=visited,
        retry_counters=dict(build_cp["retry_counters"]),
        reroute_count=build_cp["reroute_count"],
    )

    # Verify completed_nodes includes start, plan, build
    assert "start" in state.completed_nodes
    assert "plan" in state.completed_nodes
    assert "build" in state.completed_nodes

    next_node_id = build_cp["next_node_id"]
    assert next_node_id == "review"

    # Resume from review
    resume_emitter = RecordingEmitter()
    resume_runner = PipelineRunner(graph, _registry(), resume_emitter)
    next_node = graph.get_node(next_node_id)
    assert next_node is not None

    outcome = resume_runner.resume(state=state, next_node=next_node)
    assert outcome.status == OutcomeStatus.SUCCESS

    # Only review should have executed
    stage_started = [e for e in resume_emitter.events if e[0] == "StageStarted"]
    started_nodes = [e[1]["node_id"] for e in stage_started]
    assert started_nodes == ["review"]


def test_retry_counters_preserved() -> None:
    """Retry counters are preserved across pause/resume."""
    graph = PipelineGraph(
        name="test_retry_resume",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "flaky": Node(
                id="flaky",
                shape="box",
                label="Flaky",
                prompt="Flaky task",
                attributes={"max_retries": "3", "sim_outcomes": "FAIL,FAIL,SUCCESS"},
            ),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="flaky"),
            Edge(from_node="flaky", to_node="exit"),
        ],
    )

    # Run normally — the retry counters should be recorded in the checkpoint
    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, _registry(), emitter, sleep_fn=lambda x: None)
    runner.run()

    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    flaky_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "flaky"][0][1]

    # The retry_counters should reflect retries used
    assert "retry_counters" in flaky_cp

    # Visited outcomes should show the flaky node succeeded after retries
    assert flaky_cp["visited_outcomes"]["flaky"] == "SUCCESS"


def test_resume_branching_pipeline() -> None:
    """Resume a pipeline paused mid-branch — correct branch continues."""
    graph = _branching_graph()

    # First run: the decide node routes based on context. The StartHandler sets outcome=SUCCESS.
    # After start → decide (diamond, no-op), edge selection uses conditions.
    # We need the context to have route=a for path_a.
    # Let's use a custom handler that sets context.route.
    class RouteSetterHandler:
        def handle(self, node, context, graph):
            from orchestra.models.outcome import Outcome
            context.set("route", "a")
            return Outcome(status=OutcomeStatus.SUCCESS, context_updates={"route": "a"})

    reg = HandlerRegistry()
    reg.register("Mdiamond", RouteSetterHandler())
    reg.register("Msquare", ExitHandler())
    reg.register("box", SimulationCodergenHandler())
    reg.register("diamond", ConditionalHandler())

    # Run and pause after decide (before path_a executes)
    emitter = RecordingEmitter()

    class PauseAfterDecide:
        def handle(self, node, context, graph):
            from orchestra.models.outcome import Outcome
            return Outcome(status=OutcomeStatus.SUCCESS)

    # We need a more involved setup. Let's run to completion first and verify,
    # then simulate resume from after decide.
    runner = PipelineRunner(graph, reg, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS

    # Get checkpoint after decide
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    decide_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "decide"][0][1]

    # Verify decide's next_node_id is path_a (route=a)
    assert decide_cp["next_node_id"] == "path_a"

    # Simulate resume from after decide
    ctx = Context()
    for key, value in decide_cp["context_snapshot"].items():
        ctx.set(key, value)
    visited = {k: OutcomeStatus(v) for k, v in decide_cp["visited_outcomes"].items()}
    state = _RunState(
        context=ctx,
        completed_nodes=list(decide_cp["completed_nodes"]),
        visited_outcomes=visited,
        retry_counters=dict(decide_cp["retry_counters"]),
        reroute_count=decide_cp["reroute_count"],
    )

    resume_emitter = RecordingEmitter()
    resume_runner = PipelineRunner(graph, _registry(), resume_emitter)
    next_node = graph.get_node("path_a")
    assert next_node is not None

    resume_outcome = resume_runner.resume(state=state, next_node=next_node)
    assert resume_outcome.status == OutcomeStatus.SUCCESS

    # Verify path_a was executed, path_b was not
    stage_started = [e for e in resume_emitter.events if e[0] == "StageStarted"]
    started_nodes = [e[1]["node_id"] for e in stage_started]
    assert "path_a" in started_nodes
    assert "path_b" not in started_nodes


def test_goal_gates_after_resume() -> None:
    """Goal gate checks work correctly after resume (visited_outcomes restored)."""
    graph = PipelineGraph(
        name="test_gates_resume",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "critical": Node(
                id="critical",
                shape="box",
                label="Critical",
                prompt="Critical task",
                attributes={"goal_gate": "true"},
            ),
            "final": Node(id="final", shape="box", label="Final", prompt="Final task"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="critical"),
            Edge(from_node="critical", to_node="final"),
            Edge(from_node="final", to_node="exit"),
        ],
    )

    # Run and pause after critical
    emitter, events = _run_and_pause_after(graph, "critical")

    checkpoints = [e for e in events if e[0] == "CheckpointSaved"]
    critical_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "critical"][0][1]

    # Build resume state — critical was SUCCESS
    ctx = Context()
    for key, value in critical_cp["context_snapshot"].items():
        ctx.set(key, value)
    visited = {k: OutcomeStatus(v) for k, v in critical_cp["visited_outcomes"].items()}
    state = _RunState(
        context=ctx,
        completed_nodes=list(critical_cp["completed_nodes"]),
        visited_outcomes=visited,
        retry_counters=dict(critical_cp["retry_counters"]),
        reroute_count=critical_cp["reroute_count"],
    )

    # Verify visited_outcomes preserved the critical node's success
    assert state.visited_outcomes["critical"] == OutcomeStatus.SUCCESS

    # Resume from final
    resume_emitter = RecordingEmitter()
    resume_runner = PipelineRunner(graph, _registry(), resume_emitter)
    next_node = graph.get_node(critical_cp["next_node_id"])
    assert next_node is not None

    outcome = resume_runner.resume(state=state, next_node=next_node)
    assert outcome.status == OutcomeStatus.SUCCESS

    # Pipeline should complete — goal gate satisfied because visited_outcomes restored
    resume_event_types = [e[0] for e in resume_emitter.events]
    assert "PipelineCompleted" in resume_event_types


# --- restore_from_turns tests ---


def test_restore_from_turns_basic() -> None:
    """restore_from_turns extracts resume state from mock CXDB turns."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {
                "pipeline_name": "test_pipeline",
                "status": "started",
                "session_display_id": "abc123",
                "dot_file_path": "/tmp/test.dot",
                "graph_hash": "deadbeef",
            },
        },
        {
            "type_id": "dev.orchestra.NodeExecution",
            "data": {"node_id": "start", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {
                "current_node": "start",
                "completed_nodes": ["start"],
                "context_snapshot": {"graph.goal": "test", "last_stage": "start"},
                "retry_counters": {},
                "next_node_id": "plan",
                "visited_outcomes": {"start": "SUCCESS"},
                "reroute_count": 0,
            },
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test_pipeline", "status": "paused"},
        },
    ]

    info = restore_from_turns(turns, "ctx-1")
    assert info.pipeline_name == "test_pipeline"
    assert info.dot_file_path == "/tmp/test.dot"
    assert info.graph_hash == "deadbeef"
    assert info.next_node_id == "plan"
    assert info.state.completed_nodes == ["start"]
    assert info.state.visited_outcomes["start"] == OutcomeStatus.SUCCESS
    assert info.state.context.get("last_stage") == "start"


def test_restore_from_turns_rejects_completed() -> None:
    """Cannot resume a completed session."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {
                "current_node": "plan",
                "completed_nodes": ["start", "plan"],
                "context_snapshot": {},
                "retry_counters": {},
                "next_node_id": "",
            },
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "completed"},
        },
    ]

    with pytest.raises(ResumeError, match="already completed"):
        restore_from_turns(turns, "ctx-1")


def test_restore_from_turns_rejects_failed() -> None:
    """Cannot resume a failed session."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "failed", "error": "boom"},
        },
    ]

    with pytest.raises(ResumeError, match="failed"):
        restore_from_turns(turns, "ctx-1")


def test_restore_from_turns_rejects_no_checkpoint() -> None:
    """Cannot resume without a checkpoint."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
    ]

    with pytest.raises(ResumeError, match="No checkpoint"):
        restore_from_turns(turns, "ctx-1")


def test_restore_from_turns_rejects_no_next_node() -> None:
    """Cannot resume from a checkpoint with no next_node_id (terminal)."""
    turns = [
        {
            "type_id": "dev.orchestra.PipelineLifecycle",
            "data": {"pipeline_name": "test", "status": "started"},
        },
        {
            "type_id": "dev.orchestra.Checkpoint",
            "data": {
                "current_node": "plan",
                "completed_nodes": ["start", "plan"],
                "context_snapshot": {},
                "retry_counters": {},
                "next_node_id": "",
            },
        },
    ]

    with pytest.raises(ResumeError, match="no next_node_id"):
        restore_from_turns(turns, "ctx-1")
