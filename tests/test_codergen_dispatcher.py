from orchestra.backends.simulation import SimulationBackend
from orchestra.handlers.codergen_dispatcher import CodergenDispatcher
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.interactive import InteractiveHandler
from orchestra.interviewer.auto_approve import AutoApproveInterviewer
from orchestra.interviewer.models import Answer
from orchestra.interviewer.queue import QueueInterviewer
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus


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


class TestCodergenDispatcher:
    def test_standard_node_delegates_to_codergen_handler(self):
        """Node without agent.mode delegates to standard CodergenHandler."""
        backend = SimulationBackend()
        standard = CodergenHandler(backend=backend)
        interactive = InteractiveHandler(
            backend=backend,
            interviewer=AutoApproveInterviewer(),
        )
        dispatcher = CodergenDispatcher(standard=standard, interactive=interactive)

        node = Node(id="work", label="Do work", shape="box", prompt="Do something")
        graph = _make_graph(node)
        outcome = dispatcher.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.SUCCESS

    def test_interactive_node_delegates_to_interactive_handler(self):
        """Node with agent.mode=interactive delegates to InteractiveHandler."""
        backend = SimulationBackend()
        standard = CodergenHandler(backend=backend)
        interviewer = QueueInterviewer([Answer(text="/done", value="/done")])
        interactive = InteractiveHandler(
            backend=backend,
            interviewer=interviewer,
        )
        dispatcher = CodergenDispatcher(standard=standard, interactive=interactive)

        node = Node(
            id="collaborate",
            label="Collaborate",
            shape="box",
            prompt="Help the user",
            attributes={"agent.mode": "interactive"},
        )
        graph = _make_graph(node)
        outcome = dispatcher.handle(node, Context(), graph)

        assert outcome.status == OutcomeStatus.SUCCESS
        assert "interactive.history" in outcome.context_updates
