from orchestra.config.model_resolution import resolve_node_model
from orchestra.config.settings import AgentConfig, ProviderConfig, ProvidersConfig
from orchestra.models.graph import Node, PipelineGraph


def _make_providers() -> ProvidersConfig:
    return ProvidersConfig(
        default="anthropic",
        anthropic=ProviderConfig(
            models={"smart": "claude-opus-4-20250514", "worker": "claude-sonnet-4-20250514"},
        ),
        openai=ProviderConfig(
            models={"smart": "gpt-4o", "worker": "gpt-4o-mini"},
        ),
    )


def _make_node(**attrs) -> Node:
    return Node(id="test", label="test", shape="box", attributes=attrs)


def _make_graph(**graph_attrs) -> PipelineGraph:
    return PipelineGraph(
        name="test",
        nodes={},
        edges=[],
        graph_attributes=graph_attrs,
    )


class TestFullResolutionChain:
    def test_explicit_node_attribute_wins(self):
        node = _make_node(llm_model="custom-model", llm_provider="openai")
        agent = AgentConfig(model="smart", provider="anthropic")
        graph = _make_graph(llm_model="graph-model")
        model, provider = resolve_node_model(node, agent, graph, _make_providers())
        assert model == "custom-model"
        assert provider == "openai"

    def test_stylesheet_applied_as_attributes(self):
        # Stylesheet is applied as a graph transform before resolution,
        # so stylesheet values appear as node attributes
        node = _make_node(llm_model="worker")  # set by stylesheet transform
        model, provider = resolve_node_model(node, None, _make_graph(), _make_providers())
        assert model == "claude-sonnet-4-20250514"

    def test_agent_config_fallback(self):
        node = _make_node()
        agent = AgentConfig(model="smart", provider="anthropic")
        model, provider = resolve_node_model(node, agent, _make_graph(), _make_providers())
        assert model == "claude-opus-4-20250514"
        assert provider == "anthropic"

    def test_graph_level_default(self):
        node = _make_node()
        graph = _make_graph(llm_model="worker", llm_provider="openai")
        model, provider = resolve_node_model(node, None, graph, _make_providers())
        assert model == "gpt-4o-mini"
        assert provider == "openai"

    def test_provider_default_fallback(self):
        node = _make_node()
        graph = _make_graph(llm_model="smart")
        model, provider = resolve_node_model(node, None, graph, _make_providers())
        assert model == "claude-opus-4-20250514"
        assert provider == "anthropic"

    def test_no_model_configured(self):
        node = _make_node()
        model, provider = resolve_node_model(node, None, _make_graph(), _make_providers())
        assert model == ""
        assert provider == "anthropic"

    def test_explicit_overrides_agent(self):
        node = _make_node(llm_model="gpt-4o")
        agent = AgentConfig(model="smart", provider="anthropic")
        model, provider = resolve_node_model(node, agent, _make_graph(), _make_providers())
        assert model == "gpt-4o"

    def test_agent_overrides_graph(self):
        node = _make_node()
        agent = AgentConfig(model="worker")
        graph = _make_graph(llm_model="smart")
        model, provider = resolve_node_model(node, agent, graph, _make_providers())
        assert model == "claude-sonnet-4-20250514"

    def test_literal_model_passthrough(self):
        node = _make_node(llm_model="my-custom-model-v2")
        model, provider = resolve_node_model(node, None, _make_graph(), _make_providers())
        assert model == "my-custom-model-v2"
