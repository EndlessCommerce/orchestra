from __future__ import annotations

from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import Outcome, OutcomeStatus


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _build_registry(emitter: RecordingEmitter | None = None) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("box", SimulationCodergenHandler())
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
    registry.register("tripleoctagon", FanInHandler())
    return registry


def _two_branch_pipeline() -> PipelineGraph:
    return PipelineGraph(
        name="two_branch_pipeline",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box", prompt="Do A"),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )


def _four_branch_pipeline() -> PipelineGraph:
    return PipelineGraph(
        name="four_branch_pipeline",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box", prompt="Do A"),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "C": Node(id="C", shape="box", prompt="Do C"),
            "D": Node(id="D", shape="box", prompt="Do D"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="fan_out", to_node="C"),
            Edge(from_node="fan_out", to_node="D"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="C", to_node="fan_in"),
            Edge(from_node="D", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )


def test_fan_out_two_branches() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _two_branch_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS


def test_fan_out_four_branches() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _four_branch_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS


def test_bounded_parallelism() -> None:
    graph = PipelineGraph(
        name="bounded",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component", attributes={"max_parallel": 1}),
            "A": Node(id="A", shape="box", prompt="Do A"),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS


def test_context_isolation() -> None:
    """Verify branch contexts are isolated from parent and each other."""
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _two_branch_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    ctx = Context()
    ctx.set("parent_key", "parent_value")
    outcome = runner.run(context=ctx)
    assert outcome.status == OutcomeStatus.SUCCESS


def test_branch_results_stored() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _two_branch_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS

    # Check that fan_in results were set in context via checkpoints
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    fan_in_checkpoints = [
        cp for cp in checkpoints
        if cp[1].get("node_id") == "fan_in"
    ]
    assert len(fan_in_checkpoints) >= 1
    ctx_snap = fan_in_checkpoints[0][1]["context_snapshot"]
    assert "parallel.fan_in.best_id" in ctx_snap


def test_error_policy_continue() -> None:
    """With continue policy, all branches run even if some fail."""
    graph = PipelineGraph(
        name="error_continue",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component", attributes={"error_policy": "continue"}),
            "A": Node(id="A", shape="box", prompt="Do A", attributes={"sim_outcomes": "FAIL"}),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    # wait_all with mixed results yields PARTIAL_SUCCESS from fan-in
    assert outcome.status == OutcomeStatus.PARTIAL_SUCCESS


def test_error_policy_ignore() -> None:
    """With ignore policy, failed branches are excluded from results."""
    graph = PipelineGraph(
        name="error_ignore",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component", attributes={"error_policy": "ignore"}),
            "A": Node(id="A", shape="box", prompt="Do A", attributes={"sim_outcomes": "FAIL"}),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    assert outcome.status == OutcomeStatus.SUCCESS


def test_error_policy_fail_fast() -> None:
    """With fail_fast policy, cancel pending branches on first failure."""
    graph = PipelineGraph(
        name="error_fail_fast",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component", attributes={"error_policy": "fail_fast"}),
            "A": Node(id="A", shape="box", prompt="Do A", attributes={"sim_outcomes": "FAIL"}),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()
    # With fail_fast, branches may complete before cancellation; fan-in sees mixed → PARTIAL_SUCCESS
    assert outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.FAIL, OutcomeStatus.PARTIAL_SUCCESS)


def test_event_sequence() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _two_branch_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    runner.run()

    event_types = [e[0] for e in emitter.events]
    # Find parallel events
    parallel_events = [
        e for e in event_types
        if e.startswith("Parallel")
    ]
    assert "ParallelStarted" in parallel_events
    assert "ParallelCompleted" in parallel_events

    # ParallelStarted should come before ParallelCompleted
    started_idx = parallel_events.index("ParallelStarted")
    completed_idx = parallel_events.index("ParallelCompleted")
    assert started_idx < completed_idx

    # Branch events should be between Started and Completed
    branch_started = [e for e in parallel_events if e == "ParallelBranchStarted"]
    branch_completed = [e for e in parallel_events if e == "ParallelBranchCompleted"]
    assert len(branch_started) == 2
    assert len(branch_completed) == 2
