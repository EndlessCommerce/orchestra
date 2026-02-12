from orchestra.handlers.wait_human import WaitHumanHandler
from orchestra.interviewer.models import Answer, AnswerValue
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


def _make_graph_with_gate(edges_from_gate: list[Edge]) -> PipelineGraph:
    """Build a minimal graph with a hexagon gate node and outgoing edges."""
    nodes = {
        "gate": Node(id="gate", label="Review the plan", shape="hexagon"),
    }
    for edge in edges_from_gate:
        nodes[edge.to_node] = Node(id=edge.to_node, label=edge.to_node, shape="box")
    return PipelineGraph(name="test", nodes=nodes, edges=edges_from_gate)


class TestWaitHumanHandler:
    def test_derive_choices_from_edges(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
            Edge(from_node="gate", to_node="revise", label="[R] Reject"),
            Edge(from_node="gate", to_node="skip", label="[S] Skip"),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value="A")])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.SUCCESS

    def test_route_on_selection(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
            Edge(from_node="gate", to_node="revise", label="[R] Reject"),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value="R")])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.suggested_next_ids == ["revise"]

    def test_context_updated(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
            Edge(from_node="gate", to_node="revise", label="[R] Reject"),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value="A")])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.context_updates["human.gate.selected"] == "A"
        assert outcome.context_updates["human.gate.label"] == "Approve"

    def test_no_outgoing_edges_returns_fail(self):
        graph = PipelineGraph(
            name="test",
            nodes={"gate": Node(id="gate", label="Empty gate", shape="hexagon")},
            edges=[],
        )
        interviewer = QueueInterviewer([])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.FAIL
        assert "No outgoing edges" in outcome.failure_reason

    def test_timeout_with_default_choice(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
            Edge(from_node="gate", to_node="revise", label="[R] Reject"),
        ]
        graph = _make_graph_with_gate(edges)
        gate_node = graph.nodes["gate"]
        gate_node.attributes["human.default_choice"] = "A"

        interviewer = QueueInterviewer([Answer(value=AnswerValue.TIMEOUT)])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(gate_node, {}, graph)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.suggested_next_ids == ["apply"]

    def test_timeout_without_default_returns_retry(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
            Edge(from_node="gate", to_node="revise", label="[R] Reject"),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value=AnswerValue.TIMEOUT)])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.RETRY

    def test_skipped_returns_fail(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label="[A] Approve"),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value=AnswerValue.SKIPPED)])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.FAIL
        assert "skipped" in outcome.failure_reason

    def test_edge_without_label_uses_to_node(self):
        edges = [
            Edge(from_node="gate", to_node="apply", label=""),
            Edge(from_node="gate", to_node="revise", label=""),
        ]
        graph = _make_graph_with_gate(edges)
        interviewer = QueueInterviewer([Answer(value="A")])
        handler = WaitHumanHandler(interviewer)
        outcome = handler.handle(graph.nodes["gate"], {}, graph)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.suggested_next_ids == ["apply"]
