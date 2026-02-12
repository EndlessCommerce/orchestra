from __future__ import annotations

from typing import Any

from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver
from orchestra.handlers.codergen import SimulationCodergenHandler
from orchestra.handlers.fan_in_handler import FanInHandler
from orchestra.handlers.parallel_handler import ParallelHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.storage.type_bundle import from_tagged_data


class TurnRecordingClient:
    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    def append_turn(
        self, context_id: str, type_id: str, type_version: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        named_data = from_tagged_data(type_id, type_version, data)
        self.turns.append(
            {
                "context_id": context_id,
                "type_id": type_id,
                "type_version": type_version,
                "data": named_data,
            }
        )
        return {"turn_id": str(len(self.turns))}


def _parallel_graph() -> PipelineGraph:
    return PipelineGraph(
        name="cxdb_parallel",
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


def test_parallel_events_persisted_to_cxdb() -> None:
    client = TurnRecordingClient()
    observer = CxdbObserver(client=client, context_id="ctx-1")

    dispatcher = EventDispatcher()
    dispatcher.add_observer(observer)

    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("box", SimulationCodergenHandler())
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=dispatcher))
    registry.register("tripleoctagon", FanInHandler())

    graph = _parallel_graph()
    runner = PipelineRunner(graph, registry, dispatcher)
    outcome = runner.run()

    assert outcome.status == OutcomeStatus.SUCCESS

    parallel_turns = [
        t for t in client.turns
        if t["type_id"] == "dev.orchestra.ParallelExecution"
    ]
    assert len(parallel_turns) == 2  # started + completed

    started_turn = parallel_turns[0]
    assert started_turn["data"]["status"] == "started"
    assert started_turn["data"]["node_id"] == "fan_out"

    completed_turn = parallel_turns[1]
    assert completed_turn["data"]["status"] == "completed"
    assert completed_turn["data"]["success_count"] == 2
    assert completed_turn["data"]["failure_count"] == 0


def test_parallel_cxdb_fan_in_turn() -> None:
    client = TurnRecordingClient()
    observer = CxdbObserver(client=client, context_id="ctx-1")

    dispatcher = EventDispatcher()
    dispatcher.add_observer(observer)

    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("box", SimulationCodergenHandler())
    registry.register("component", ParallelHandler(handler_registry=registry, event_emitter=dispatcher))
    registry.register("tripleoctagon", FanInHandler())

    graph = _parallel_graph()
    runner = PipelineRunner(graph, registry, dispatcher)
    runner.run()

    # Fan-in should produce a StageCompleted node execution turn
    node_exec_turns = [
        t for t in client.turns
        if t["type_id"] == "dev.orchestra.NodeExecution"
        and t["data"].get("node_id") == "fan_in"
    ]
    assert len(node_exec_turns) >= 1
    fan_in_turn = node_exec_turns[-1]
    assert fan_in_turn["data"]["status"] in ("SUCCESS", "PARTIAL_SUCCESS")
