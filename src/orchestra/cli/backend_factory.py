from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from orchestra.config.settings import OrchestraConfig


def build_backend(config: OrchestraConfig):
    """Construct the appropriate backend based on config."""
    from orchestra.backends.simulation import SimulationBackend

    backend_name = config.backend

    if backend_name == "simulation" or not backend_name:
        return SimulationBackend()

    if backend_name == "direct":
        from orchestra.backends.direct_llm import DirectLLMBackend

        chat_model = build_chat_model(config)
        return DirectLLMBackend(chat_model=chat_model)

    if backend_name == "langgraph":
        from orchestra.backends.langgraph_backend import LangGraphBackend

        chat_model = build_chat_model(config)
        return LangGraphBackend(chat_model=chat_model)

    if backend_name == "cli":
        from orchestra.backends.cli_agent import CLIAgentBackend

        return CLIAgentBackend()

    typer.echo(f"Error: Unknown backend '{backend_name}'. Use: simulation, direct, langgraph, cli")
    raise typer.Exit(code=1)


def build_chat_model(config: OrchestraConfig):
    """Build a LangChain chat model from config."""
    from orchestra.config.providers import get_provider_settings, resolve_model, resolve_provider

    provider_name = resolve_provider("", config.providers)
    model_name = resolve_model("smart", provider_name, config.providers)
    settings = get_provider_settings(provider_name, config.providers)

    if provider_name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            **{k: v for k, v in settings.items() if k in ("max_tokens",)},
        )

    if provider_name == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            **{k: v for k, v in settings.items() if k in ("max_tokens",)},
        )

    from langchain_openai import ChatOpenAI

    api_base = settings.get("api_base", "")
    kwargs = {"model": model_name}
    if api_base:
        kwargs["base_url"] = api_base
    return ChatOpenAI(**kwargs)
