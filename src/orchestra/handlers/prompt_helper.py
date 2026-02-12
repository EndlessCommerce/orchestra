from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestra.config.settings import AgentConfig, OrchestraConfig
    from orchestra.models.context import Context
    from orchestra.models.graph import Node


def get_agent_config(node: Node, config: OrchestraConfig | None) -> AgentConfig | None:
    if config is None:
        return None
    agent_name = node.attributes.get("agent", "")
    if agent_name and agent_name in config.agents:
        return config.agents[agent_name]
    return None


def compose_node_prompt(node: Node, context: Context, config: OrchestraConfig | None) -> str:
    prompt = node.prompt

    agent_config = get_agent_config(node, config)
    if agent_config is not None and config is not None:
        from orchestra.prompts.engine import compose_prompt

        composed = compose_prompt(
            agent_config,
            context=context.snapshot(),
        )
        if composed:
            prompt = composed

    return prompt
