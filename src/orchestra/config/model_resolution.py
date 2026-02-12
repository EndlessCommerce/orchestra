from __future__ import annotations

from typing import TYPE_CHECKING

from orchestra.config.providers import resolve_model, resolve_provider

if TYPE_CHECKING:
    from orchestra.config.settings import AgentConfig, ProvidersConfig
    from orchestra.models.graph import Node, PipelineGraph


def resolve_node_model(
    node: Node,
    agent_config: AgentConfig | None,
    graph: PipelineGraph,
    providers_config: ProvidersConfig,
) -> tuple[str, str]:
    # 1. Explicit node attribute
    model = node.attributes.get("llm_model", "")
    provider_name = node.attributes.get("llm_provider", "")

    # 2. (Stylesheet already applied as a graph transform before this point)

    # 3. Agent config
    if not model and agent_config is not None:
        model = agent_config.model
    if not provider_name and agent_config is not None:
        provider_name = agent_config.provider

    # 4. Graph-level default
    if not model:
        model = graph.graph_attributes.get("llm_model", "")
    if not provider_name:
        provider_name = graph.graph_attributes.get("llm_provider", "")

    # 5. Provider default
    provider_name = resolve_provider(provider_name, providers_config)

    # Resolve alias to concrete model string
    if model:
        model = resolve_model(model, provider_name, providers_config)

    return model, provider_name
