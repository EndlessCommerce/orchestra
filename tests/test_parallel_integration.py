from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.registry import HandlerRegistry, default_registry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import parse_dot

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _build_registry(emitter: RecordingEmitter) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("box", SimulationCodergenHandler())
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=emitter))
    registry.register("tripleoctagon", FanInHandler())
    return registry


def _full_pipeline() -> PipelineGraph:
    """start -> fan_out -> [A, B, C] -> fan_in -> synthesize -> exit"""
    return PipelineGraph(
        name="full_parallel",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component"),
            "A": Node(id="A", shape="box", prompt="Do A"),
            "B": Node(id="B", shape="box", prompt="Do B"),
            "C": Node(id="C", shape="box", prompt="Do C"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "synthesize": Node(id="synthesize", shape="box", prompt="Synthesize results"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="A"),
            Edge(from_node="fan_out", to_node="B"),
            Edge(from_node="fan_out", to_node="C"),
            Edge(from_node="A", to_node="fan_in"),
            Edge(from_node="B", to_node="fan_in"),
            Edge(from_node="C", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="synthesize"),
            Edge(from_node="synthesize", to_node="exit"),
        ],
    )


def test_full_parallel_pipeline() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _full_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    # Verify all branches executed
    branch_completed = [
        e for e in emitter.events if e[0] == "ParallelBranchCompleted"
    ]
    assert len(branch_completed) == 3

    # Verify fan-in and synthesize ran
    stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
    completed_nodes = [e[1]["node_id"] for e in stage_completed]
    assert "fan_in" in completed_nodes
    assert "synthesize" in completed_nodes


def test_parallel_from_dot_fixture() -> None:
    source = (FIXTURES / "test-parallel.dot").read_text()
    graph = parse_dot(source)

    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    branch_completed = [
        e for e in emitter.events if e[0] == "ParallelBranchCompleted"
    ]
    assert len(branch_completed) == 3

    branch_ids = {e[1]["branch_id"] for e in branch_completed}
    assert branch_ids == {"security", "performance", "style"}


def test_parallel_with_mixed_outcomes() -> None:
    graph = PipelineGraph(
        name="mixed_outcomes",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component"),
            "ok": Node(id="ok", shape="box", prompt="Do ok"),
            "bad": Node(id="bad", shape="box", prompt="Do bad", attributes={"sim_outcomes": "FAIL"}),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="ok"),
            Edge(from_node="fan_out", to_node="bad"),
            Edge(from_node="ok", to_node="fan_in"),
            Edge(from_node="bad", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )

    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    # Fan-in with wait_all and mixed results → PARTIAL_SUCCESS
    assert outcome.status == OutcomeStatus.PARTIAL_SUCCESS


def test_parallel_event_sequence() -> None:
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _full_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    runner.run()

    event_types = [e[0] for e in emitter.events]

    # Find indices of parallel events
    parallel_started_idx = event_types.index("ParallelStarted")
    parallel_completed_idx = event_types.index("ParallelCompleted")

    branch_started_indices = [
        i for i, t in enumerate(event_types) if t == "ParallelBranchStarted"
    ]
    branch_completed_indices = [
        i for i, t in enumerate(event_types) if t == "ParallelBranchCompleted"
    ]

    # All branch starts after parallel start
    for idx in branch_started_indices:
        assert idx > parallel_started_idx

    # All branch completions before parallel completion
    for idx in branch_completed_indices:
        assert idx < parallel_completed_idx

    assert len(branch_started_indices) == 3
    assert len(branch_completed_indices) == 3


def test_parallel_timing_concurrent() -> None:
    """Verify branches start before any complete (true concurrency)."""
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _full_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    runner.run()

    event_types = [e[0] for e in emitter.events]

    branch_started_indices = [
        i for i, t in enumerate(event_types) if t == "ParallelBranchStarted"
    ]
    branch_completed_indices = [
        i for i, t in enumerate(event_types) if t == "ParallelBranchCompleted"
    ]

    if len(branch_started_indices) >= 2:
        # At least 2 branches should start before the first branch completes
        # (this verifies concurrency, not sequential execution)
        first_completion = min(branch_completed_indices)
        starts_before_first_completion = sum(
            1 for idx in branch_started_indices if idx < first_completion
        )
        assert starts_before_first_completion >= 2


def test_parallel_results_flow_to_downstream() -> None:
    """Synthesize node can access parallel.fan_in.best_id from context."""
    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    graph = _full_pipeline()
    runner = PipelineRunner(graph, registry, emitter)
    runner.run()

    # Find the checkpoint after fan_in
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    fan_in_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "fan_in"]
    assert len(fan_in_cp) >= 1
    ctx_snap = fan_in_cp[0][1]["context_snapshot"]
    assert "parallel.fan_in.best_id" in ctx_snap
    assert ctx_snap["parallel.fan_in.best_id"] in ("A", "B", "C")


def test_parallel_with_retry_in_branch() -> None:
    """Branch with retry succeeds after initial failure."""
    graph = PipelineGraph(
        name="retry_branch",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fan_out": Node(id="fan_out", shape="component"),
            "retry_node": Node(
                id="retry_node",
                shape="box",
                prompt="Do with retry",
                attributes={"sim_outcomes": "FAIL,SUCCESS", "max_retries": "2"},
            ),
            "stable": Node(id="stable", shape="box", prompt="Do stable"),
            "fan_in": Node(id="fan_in", shape="tripleoctagon"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fan_out"),
            Edge(from_node="fan_out", to_node="retry_node"),
            Edge(from_node="fan_out", to_node="stable"),
            Edge(from_node="retry_node", to_node="fan_in"),
            Edge(from_node="stable", to_node="fan_in"),
            Edge(from_node="fan_in", to_node="exit"),
        ],
    )

    emitter = RecordingEmitter()
    registry = _build_registry(emitter)
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    # Verify retry events happened within the branch
    retry_events = [e for e in emitter.events if e[0] == "StageRetrying"]
    assert len(retry_events) >= 1


def test_default_registry_registers_parallel_handlers() -> None:
    """Verify default_registry() includes component and tripleoctagon."""
    registry = default_registry()
    assert registry.get("component") is not None
    assert registry.get("tripleoctagon") is not None
    assert isinstance(registry.get("component"), ParallelHandler)
    assert isinstance(registry.get("tripleoctagon"), FanInHandler)
