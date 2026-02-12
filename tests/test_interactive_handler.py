from orchestra.backends.simulation import SimulationBackend
from orchestra.handlers.interactive import InteractiveHandler
from orchestra.interviewer.models import Answer
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


def _make_interactive_node() -> Node:
    return Node(
        id="collaborate",
        label="Collaborate",
        shape="box",
        prompt="Help the user",
        attributes={"agent.mode": "interactive"},
    )


def _make_graph(node: Node) -> PipelineGraph:
    return PipelineGraph(
        name="test",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            node.id: node,
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node=node.id),
            Edge(from_node=node.id, to_node="exit"),
        ],
    )


class TestInteractiveHandler:
    def test_done_command_completes_successfully(self):
        """Agent sends → human says /done → SUCCESS."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([Answer(text="/done", value="/done")])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)
        outcome = handler.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.SUCCESS

    def test_approve_command_completes_successfully(self):
        """Agent sends → human says /approve → SUCCESS."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([Answer(text="/approve", value="/approve")])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)
        outcome = handler.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.SUCCESS

    def test_reject_command_fails(self):
        """Agent sends → human says /reject → FAIL."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([Answer(text="/reject", value="/reject")])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)
        outcome = handler.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.FAIL
        assert "rejected" in outcome.failure_reason

    def test_multi_turn_exchange(self):
        """Agent sends → human responds → agent sends → human /done → SUCCESS."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([
            Answer(text="tell me more", value="tell me more"),
            Answer(text="/done", value="/done"),
        ])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)
        outcome = handler.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.SUCCESS
        history = outcome.context_updates.get("interactive.history")
        assert history is not None
        assert len(history) == 2

    def test_history_stored_in_context_updates(self):
        """Conversation history is stored in context_updates."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([
            Answer(text="a message", value="a message"),
            Answer(text="/done", value="/done"),
        ])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)
        outcome = handler.handle(node, Context(), graph)

        history = outcome.context_updates["interactive.history"]
        assert len(history) == 2
        assert history[0]["human"] == "a message"
        assert "agent" in history[0]

    def test_resume_with_prior_history(self):
        """Handler replays history from context and continues."""
        backend = SimulationBackend()
        interviewer = QueueInterviewer([Answer(text="/done", value="/done")])
        handler = InteractiveHandler(backend=backend, interviewer=interviewer)

        node = _make_interactive_node()
        graph = _make_graph(node)

        # Simulate resuming with prior history
        context = Context()
        context.set("interactive.history", [
            {"agent": "Hello, how can I help?", "human": "Make a plan"},
        ])

        outcome = handler.handle(node, context, graph)

        assert outcome.status == OutcomeStatus.SUCCESS
        history = outcome.context_updates["interactive.history"]
        # Prior history (1 entry) + new turn ending with /done (1 entry)
        assert len(history) == 2
