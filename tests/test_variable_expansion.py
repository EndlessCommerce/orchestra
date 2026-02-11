from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.transforms.variable_expansion import expand_variables


def test_goal_expansion() -> None:
    graph = PipelineGraph(
        name="test",
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

    result = expand_variables(graph)
    assert result.nodes["plan"].prompt == "Implement: build widget"


def test_no_goal_in_prompt_unchanged() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", prompt="Do the thing"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
        graph_attributes={"goal": "build widget"},
    )

    result = expand_variables(graph)
    assert result.nodes["plan"].prompt == "Do the thing"


def test_missing_goal_replaced_with_empty() -> None:
    graph = PipelineGraph(
        name="test",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "plan": Node(id="plan", shape="box", prompt="Implement: $goal"),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="plan"),
            Edge(from_node="plan", to_node="exit"),
        ],
    )

    result = expand_variables(graph)
    assert result.nodes["plan"].prompt == "Implement: "
