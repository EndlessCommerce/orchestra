from __future__ import annotations

from unittest.mock import MagicMock, call

from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.events.types import (
    CheckpointSaved,
    PipelineCompleted,
    PipelineStarted,
    StageCompleted,
    StageStarted,
)


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list = []

    def on_event(self, event) -> None:
        self.events.append(event)


def test_dispatcher_sends_to_all_observers() -> None:
    dispatcher = EventDispatcher()
    obs1 = RecordingObserver()
    obs2 = RecordingObserver()
    dispatcher.add_observer(obs1)
    dispatcher.add_observer(obs2)

    dispatcher.emit("PipelineStarted", pipeline_name="test", goal="do stuff")

    assert len(obs1.events) == 1
    assert len(obs2.events) == 1
    assert isinstance(obs1.events[0], PipelineStarted)
    assert obs1.events[0].pipeline_name == "test"


def test_stdout_observer_formats_events(capsys) -> None:
    observer = StdoutObserver()

    observer.on_event(PipelineStarted(pipeline_name="my_pipe", goal="test goal"))
    observer.on_event(StageStarted(node_id="plan", handler_type="box"))
    observer.on_event(
        StageCompleted(
            node_id="plan",
            handler_type="box",
            status="SUCCESS",
            duration_ms=42,
            response="[Simulated] Response for stage: plan",
        )
    )
    observer.on_event(PipelineCompleted(pipeline_name="my_pipe", duration_ms=100))

    output = capsys.readouterr().out
    assert "Started: my_pipe" in output
    assert "plan" in output
    assert "Completed" in output


def test_cxdb_observer_maps_events() -> None:
    mock_client = MagicMock()

    observer = CxdbObserver(mock_client, context_id="99")

    observer.on_event(PipelineStarted(pipeline_name="test", goal="g"))
    observer.on_event(StageStarted(node_id="plan", handler_type="box"))
    observer.on_event(
        StageCompleted(
            node_id="plan",
            handler_type="box",
            status="SUCCESS",
            prompt="do it",
            response="done",
            outcome="SUCCESS",
            duration_ms=10,
        )
    )
    observer.on_event(
        CheckpointSaved(
            node_id="plan",
            completed_nodes=["start", "plan"],
            context_snapshot={"outcome": "SUCCESS"},
        )
    )
    observer.on_event(PipelineCompleted(pipeline_name="test", duration_ms=50))

    assert mock_client.append_turn.call_count == 5

    calls = mock_client.append_turn.call_args_list
    # PipelineStarted → PipelineLifecycle
    assert calls[0].kwargs["type_id"] == "dev.orchestra.PipelineLifecycle"
    assert calls[0].kwargs["data"]["status"] == "started"

    # StageStarted → NodeExecution
    assert calls[1].kwargs["type_id"] == "dev.orchestra.NodeExecution"
    assert calls[1].kwargs["data"]["status"] == "started"

    # StageCompleted → NodeExecution
    assert calls[2].kwargs["type_id"] == "dev.orchestra.NodeExecution"
    assert calls[2].kwargs["data"]["prompt"] == "do it"
    assert calls[2].kwargs["data"]["response"] == "done"

    # CheckpointSaved → Checkpoint
    assert calls[3].kwargs["type_id"] == "dev.orchestra.Checkpoint"
    assert calls[3].kwargs["data"]["current_node"] == "plan"

    # PipelineCompleted → PipelineLifecycle
    assert calls[4].kwargs["type_id"] == "dev.orchestra.PipelineLifecycle"
    assert calls[4].kwargs["data"]["status"] == "completed"
