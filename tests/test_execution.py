from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.handlers.registry import default_registry
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import parse_dot
from orchestra.transforms.variable_expansion import expand_variables

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def test_execute_3_node_linear_pipeline() -> None:
    graph = PipelineGraph(
        name="test_3",
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

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, default_registry(), emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
    completed_nodes = [e[1]["node_id"] for e in stage_completed]
    assert completed_nodes == ["start", "plan"]


def test_execute_5_node_linear_pipeline() -> None:
    source = (FIXTURES / "test-linear.dot").read_text()
    graph = parse_dot(source)
    graph = expand_variables(graph)

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, default_registry(), emitter)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
    completed_nodes = [e[1]["node_id"] for e in stage_completed]
    assert completed_nodes == ["start", "plan", "build", "review"]


def test_simulation_mode_output() -> None:
    graph = PipelineGraph(
        name="test_sim",
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

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, default_registry(), emitter)
    runner.run()

    stage_completed = [e for e in emitter.events if e[0] == "StageCompleted"]
    plan_event = [e for e in stage_completed if e[1]["node_id"] == "plan"][0]
    assert "[Simulated] Response for stage: plan" in plan_event[1]["response"]


def test_variable_expansion_in_execution() -> None:
    graph = PipelineGraph(
        name="test_var",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", prompt="Implement: $goal"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
        graph_attributes={"goal": "build widget"},
    )
    graph = expand_variables(graph)
    assert graph.nodes["plan"].prompt == "Implement: build widget"


def test_context_propagation_between_nodes() -> None:
    graph = PipelineGraph(
        name="test_ctx",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "a": Node(id="a", shape="box", label="A", prompt="A"),
            "b": Node(id="b", shape="box", label="B", prompt="B"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="a"),
            Edge(from_node="a", to_node="b"),
            Edge(from_node="b", to_node="exit"),
        ],
    )

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, default_registry(), emitter)
    runner.run()

    checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
    # After node 'b', the context should contain last_stage set by 'a' previously
    b_checkpoint = [cp for cp in checkpoints if cp[1]["node_id"] == "b"][0]
    snapshot = b_checkpoint[1]["context_snapshot"]
    assert snapshot.get("last_stage") == "b"
    assert "last_response" in snapshot


def test_events_emitted_in_correct_order() -> None:
    graph = PipelineGraph(
        name="test_order",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", label="Plan", prompt="Plan"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
    )

    emitter = RecordingEmitter()
    runner = PipelineRunner(graph, default_registry(), emitter)
    runner.run()

    event_types = [e[0] for e in emitter.events]
    assert event_types[0] == "PipelineStarted"
    assert event_types[-1] == "PipelineCompleted"

    # Each node should have StageStarted, StageCompleted, CheckpointSaved
    assert "StageStarted" in event_types
    assert "StageCompleted" in event_types
    assert "CheckpointSaved" in event_types

    # Pipeline events bracket the stage events
    pipeline_start_idx = event_types.index("PipelineStarted")
    pipeline_end_idx = event_types.index("PipelineCompleted")
    stage_indices = [i for i, t in enumerate(event_types) if t.startswith("Stage")]
    for idx in stage_indices:
        assert pipeline_start_idx < idx < pipeline_end_idx
