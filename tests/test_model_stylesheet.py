from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.transforms.model_stylesheet import (
    apply_model_stylesheet,
    parse_stylesheet,
)


def _make_graph(nodes: dict[str, dict], stylesheet: str = "") -> PipelineGraph:
    graph_nodes = {}
    for nid, attrs in nodes.items():
        graph_nodes[nid] = Node(
            id=nid,
            label=nid,
            shape=attrs.get("shape", "box"),
            attributes={k: v for k, v in attrs.items() if k != "shape"},
        )
    return PipelineGraph(
        name="test",
        nodes=graph_nodes,
        edges=[],
        graph_attributes={"model_stylesheet": stylesheet} if stylesheet else {},
    )


class TestParseStylesheet:
    def test_universal_selector(self):
        rules = parse_stylesheet("* { llm_model: smart; }")
        assert len(rules) == 1
        assert rules[0].selector_type == "universal"
        assert rules[0].properties["llm_model"] == "smart"

    def test_class_selector(self):
        rules = parse_stylesheet(".code { llm_model: worker; }")
        assert len(rules) == 1
        assert rules[0].selector_type == "class"
        assert rules[0].selector_value == "code"
        assert rules[0].properties["llm_model"] == "worker"

    def test_id_selector(self):
        rules = parse_stylesheet("#review { llm_model: gpt-4o; }")
        assert len(rules) == 1
        assert rules[0].selector_type == "id"
        assert rules[0].selector_value == "review"
        assert rules[0].properties["llm_model"] == "gpt-4o"

    def test_multiple_properties(self):
        rules = parse_stylesheet("* { llm_model: smart; llm_provider: anthropic; }")
        assert rules[0].properties["llm_model"] == "smart"
        assert rules[0].properties["llm_provider"] == "anthropic"

    def test_multiple_rules(self):
        text = "* { llm_model: smart; }\n.code { llm_model: worker; }"
        rules = parse_stylesheet(text)
        assert len(rules) == 2

    def test_unknown_property_ignored(self):
        rules = parse_stylesheet("* { llm_model: smart; color: red; }")
        assert "llm_model" in rules[0].properties
        assert "color" not in rules[0].properties

    def test_empty_stylesheet(self):
        rules = parse_stylesheet("")
        assert rules == []


class TestApplyStylesheet:
    def test_universal_applies_to_all(self):
        graph = _make_graph(
            {"a": {}, "b": {}},
            stylesheet="* { llm_model: smart; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["a"].attributes["llm_model"] == "smart"
        assert result.nodes["b"].attributes["llm_model"] == "smart"

    def test_class_selector_applies_to_matching(self):
        graph = _make_graph(
            {"a": {"class": "code"}, "b": {"class": "review"}},
            stylesheet=".code { llm_model: worker; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["a"].attributes["llm_model"] == "worker"
        assert "llm_model" not in result.nodes["b"].attributes

    def test_id_selector_applies_to_specific(self):
        graph = _make_graph(
            {"review": {}, "code": {}},
            stylesheet="#review { llm_model: gpt-4o; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["review"].attributes["llm_model"] == "gpt-4o"
        assert "llm_model" not in result.nodes["code"].attributes

    def test_specificity_order(self):
        graph = _make_graph(
            {"review": {"class": "code"}},
            stylesheet=(
                "* { llm_model: cheap; }\n"
                ".code { llm_model: worker; }\n"
                "#review { llm_model: smart; }"
            ),
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["review"].attributes["llm_model"] == "smart"

    def test_explicit_override_preserved(self):
        graph = _make_graph(
            {"a": {"llm_model": "custom-model"}},
            stylesheet="* { llm_model: smart; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["a"].attributes["llm_model"] == "custom-model"

    def test_multiple_classes(self):
        graph = _make_graph(
            {"a": {"class": "code,critical"}},
            stylesheet=".code { llm_model: worker; }\n.critical { llm_provider: anthropic; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["a"].attributes["llm_model"] == "worker"
        assert result.nodes["a"].attributes["llm_provider"] == "anthropic"

    def test_no_stylesheet_unchanged(self):
        graph = _make_graph({"a": {}})
        result = apply_model_stylesheet(graph)
        assert "llm_model" not in result.nodes["a"].attributes

    def test_reasoning_effort_property(self):
        graph = _make_graph(
            {"a": {}},
            stylesheet="* { reasoning_effort: high; }",
        )
        result = apply_model_stylesheet(graph)
        assert result.nodes["a"].attributes["reasoning_effort"] == "high"
