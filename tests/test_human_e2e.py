"""End-to-end integration tests for human-in-the-loop pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestra.backends.simulation import SimulationBackend
from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.registry import default_registry
from orchestra.interviewer.auto_approve import AutoApproveInterviewer
from orchestra.interviewer.models import Answer, AnswerValue
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import parse_dot

FIXTURES = Path(__file__).parent / "fixtures"


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


class TestHumanGateApprove:
    """Pipeline with human gate: QueueInterviewer answers 'approve' → routes to exit."""

    def test_approve_routes_through_gate(self):
        source = (FIXTURES / "test-human-gate.dot").read_text()
        graph = parse_dot(source)

        interviewer = QueueInterviewer([Answer(value="A")])
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "do_work" in completed
        assert "review_gate" in completed
        assert "apply" in completed


class TestHumanGateReject:
    """Pipeline with human gate: QueueInterviewer answers 'reject' → routes to revise."""

    def test_reject_routes_to_revise_then_approve(self):
        source = (FIXTURES / "test-human-gate.dot").read_text()
        graph = parse_dot(source)

        # First gate: Reject → revise; second gate: Approve → apply
        interviewer = QueueInterviewer([
            Answer(value="R"),
            Answer(value="A"),
        ])
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "revise" in completed
        assert "apply" in completed


class TestHumanGateAutoApprove:
    """AutoApproveInterviewer selects first option → pipeline completes."""

    def test_auto_approve_selects_first_option(self):
        source = (FIXTURES / "test-human-gate.dot").read_text()
        graph = parse_dot(source)

        interviewer = AutoApproveInterviewer()
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "review_gate" in completed


class TestMultipleHumanGates:
    """Pipeline with 2 human gates: QueueInterviewer with 2 answers → both route correctly."""

    def test_two_gates_both_continue(self):
        source = (FIXTURES / "test-multiple-gates.dot").read_text()
        graph = parse_dot(source)

        # Both gates select "Continue" (C)
        interviewer = QueueInterviewer([
            Answer(value="C"),
            Answer(value="C"),
        ])
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "step1" in completed
        assert "gate1" in completed
        assert "step2" in completed
        assert "gate2" in completed
        assert "finish" in completed

    def test_second_gate_stops(self):
        source = (FIXTURES / "test-multiple-gates.dot").read_text()
        graph = parse_dot(source)

        # First gate: Continue, second gate: Stop
        interviewer = QueueInterviewer([
            Answer(value="C"),
            Answer(value="S"),
        ])
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "step2" in completed
        assert "gate2" in completed
        assert "finish" not in completed


class TestInteractiveNodeE2E:
    """Pipeline with interactive codergen node using QueueInterviewer + SimulationBackend."""

    def test_interactive_node_multi_turn(self):
        source = (FIXTURES / "test-interactive.dot").read_text()
        graph = parse_dot(source)

        # Interactive node: one exchange then /done
        interviewer = QueueInterviewer([
            Answer(text="tell me more", value="tell me more"),
            Answer(text="/done", value="/done"),
        ])
        backend = SimulationBackend()
        registry = default_registry(backend=backend, interviewer=interviewer)
        emitter = RecordingEmitter()

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "collaborate" in completed
        assert "summarize" in completed
