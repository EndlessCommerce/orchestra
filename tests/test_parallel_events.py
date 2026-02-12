from __future__ import annotations

from typing import Any

from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.types import (
    EVENT_TYPE_MAP,
    Event,
    ParallelBranchCompleted,
    ParallelBranchStarted,
    ParallelCompleted,
    ParallelStarted,
)


def test_parallel_started_instantiation() -> None:
    event = ParallelStarted(node_id="fan_out", branch_count=3)
    assert event.node_id == "fan_out"
    assert event.branch_count == 3
    assert event.event_type == "ParallelStarted"


def test_parallel_branch_started_instantiation() -> None:
    event = ParallelBranchStarted(
        node_id="fan_out", branch_id="security", first_node_id="security_review"
    )
    assert event.branch_id == "security"
    assert event.first_node_id == "security_review"


def test_parallel_branch_completed_instantiation() -> None:
    event = ParallelBranchCompleted(
        node_id="fan_out",
        branch_id="security",
        status="SUCCESS",
        duration_ms=150,
        failure_reason="",
    )
    assert event.status == "SUCCESS"
    assert event.duration_ms == 150


def test_parallel_completed_instantiation() -> None:
    event = ParallelCompleted(
        node_id="fan_out",
        success_count=2,
        failure_count=1,
        duration_ms=500,
    )
    assert event.success_count == 2
    assert event.failure_count == 1


def test_event_type_map_registration() -> None:
    assert "ParallelStarted" in EVENT_TYPE_MAP
    assert "ParallelBranchStarted" in EVENT_TYPE_MAP
    assert "ParallelBranchCompleted" in EVENT_TYPE_MAP
    assert "ParallelCompleted" in EVENT_TYPE_MAP

    assert EVENT_TYPE_MAP["ParallelStarted"] is ParallelStarted
    assert EVENT_TYPE_MAP["ParallelBranchStarted"] is ParallelBranchStarted
    assert EVENT_TYPE_MAP["ParallelBranchCompleted"] is ParallelBranchCompleted
    assert EVENT_TYPE_MAP["ParallelCompleted"] is ParallelCompleted


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def on_event(self, event: Event) -> None:
        self.events.append(event)


def test_dispatcher_delivers_parallel_events() -> None:
    dispatcher = EventDispatcher()
    observer = RecordingObserver()
    dispatcher.add_observer(observer)

    dispatcher.emit("ParallelStarted", node_id="fan_out", branch_count=2)
    dispatcher.emit("ParallelBranchStarted", node_id="fan_out", branch_id="A", first_node_id="A")
    dispatcher.emit("ParallelBranchCompleted", node_id="fan_out", branch_id="A", status="SUCCESS", duration_ms=100)
    dispatcher.emit("ParallelCompleted", node_id="fan_out", success_count=2, failure_count=0, duration_ms=200)

    assert len(observer.events) == 4
    assert isinstance(observer.events[0], ParallelStarted)
    assert isinstance(observer.events[1], ParallelBranchStarted)
    assert isinstance(observer.events[2], ParallelBranchCompleted)
    assert isinstance(observer.events[3], ParallelCompleted)
