from __future__ import annotations

from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.registry import default_registry
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


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


def test_3_node_linear_pipeline() -> None:
    graph = _linear_graph_3()
    emitter = RecordingEmitter()
    registry = default_registry()

    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    event_types = [e[0] for e in emitter.events]
    assert event_types[0] == "PipelineStarted"
    assert event_types[-1] == "PipelineCompleted"

    # start (StageStarted + StageCompleted + Checkpoint) + plan (same)
    stage_started = [e for e in emitter.events if e[0] == "StageStarted"]
    assert len(stage_started) == 2  # start + plan (exit is terminal)


def test_5_node_linear_pipeline() -> None:
    graph = _linear_graph_5()
    emitter = RecordingEmitter()
    registry = default_registry()

    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
    assert len(stage_completed) == 4  # start, plan, build, review


def test_context_propagation() -> None:
    graph = _linear_graph_5()
    emitter = RecordingEmitter()
    registry = default_registry()

    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    # Verify checkpoints show context updates
    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    assert len(checkpoints) >= 2

    # Last checkpoint should have context with last_stage set
    last_cp = checkpoints[-1][1]
    assert "last_stage" in last_cp["context_snapshot"]


def test_handler_fail_emits_pipeline_failed() -> None:
    from orchestra.handlers.registry import HandlerRegistry
    from orchestra.models.context import Context
    from orchestra.models.outcome import Outcome

    class FailHandler:
        def handle(self, node, context, graph):
            return Outcome(
                status=OutcomeStatus.FAIL,
                failure_reason="intentional failure",
            )

    graph = PipelineGraph(
        name="test_fail",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "fail_node": Node(id="fail_node", shape="box"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="fail_node"),
            # No edge from fail_node to exit
        ],
    )

    registry = HandlerRegistry()
    from orchestra.handlers.start import StartHandler
    registry.register("Mdiamond", StartHandler())
    registry.register("box", FailHandler())

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, registry, emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.FAIL

    event_types = [e[0] for e in emitter.events]
    assert "PipelineFailed" in event_types
