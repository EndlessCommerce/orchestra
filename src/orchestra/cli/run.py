from __future__ import annotations

import signal
import uuid
from pathlib import Path

import blake3
import typer

from orchestra.config.settings import OrchestraConfig, load_config
from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import DotParseError, parse_dot
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import publish_orchestra_types
from orchestra.transforms.model_stylesheet import apply_model_stylesheet
from orchestra.transforms.variable_expansion import expand_variables
from orchestra.validation.validator import ValidationError, validate_or_raise


def _build_backend(config: OrchestraConfig):
    """Construct the appropriate backend based on config."""
    from orchestra.backends.simulation import SimulationBackend

    backend_name = config.backend

    if backend_name == "simulation" or not backend_name:
        return SimulationBackend()

    if backend_name == "direct":
        from orchestra.backends.direct_llm import DirectLLMBackend

        chat_model = _build_chat_model(config)
        return DirectLLMBackend(chat_model=chat_model)

    if backend_name == "langgraph":
        from orchestra.backends.langgraph_backend import LangGraphBackend

        chat_model = _build_chat_model(config)
        return LangGraphBackend(chat_model=chat_model)

    if backend_name == "cli":
        from orchestra.backends.cli_agent import CLIAgentBackend

        return CLIAgentBackend()

    typer.echo(f"Error: Unknown backend '{backend_name}'. Use: simulation, direct, langgraph, cli")
    raise typer.Exit(code=1)


def _build_chat_model(config: OrchestraConfig):
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


def run(pipeline: Path) -> None:
    """Execute a DOT pipeline."""
    if not pipeline.exists():
        typer.echo(f"Error: file not found: {pipeline}")
        raise typer.Exit(code=1)

    # Load config
    config = load_config()

    # Parse
    source = pipeline.read_text()
    try:
        graph = parse_dot(source)
    except DotParseError as e:
        typer.echo(f"Parse error: {e}")
        raise typer.Exit(code=1)

    # Validate
    try:
        validate_or_raise(graph)
    except ValidationError as e:
        for d in e.diagnostics.errors:
            typer.echo(f"  ERROR: [{d.rule}] {d.message}")
            if d.suggestion:
                typer.echo(f"    Suggestion: {d.suggestion}")
        raise typer.Exit(code=1)

    # Transform
    graph = expand_variables(graph)
    graph = apply_model_stylesheet(graph)

    # Compute graph hash for resume verification
    graph_hash = blake3.blake3(pipeline.read_bytes()).hexdigest()
    dot_file_path = str(pipeline.resolve())

    # Connect to CXDB
    client = CxdbClient(config.cxdb.url)
    try:
        client.health_check()
    except CxdbConnectionError:
        typer.echo(
            "Error: Cannot connect to CXDB.\n"
            "Run 'orchestra doctor' for setup instructions."
        )
        raise typer.Exit(code=1)
    except CxdbError as e:
        typer.echo(f"Error: CXDB health check failed: {e}")
        raise typer.Exit(code=1)

    # Publish type bundle (idempotent)
    try:
        publish_orchestra_types(client)
    except CxdbError as e:
        typer.echo(f"Error: Failed to publish type bundle: {e}")
        raise typer.Exit(code=1)

    # Create CXDB context
    try:
        ctx_result = client.create_context()
        context_id = str(ctx_result.get("context_id", ctx_result.get("id", "unknown")))
    except CxdbError as e:
        typer.echo(f"Error: Failed to create CXDB context: {e}")
        raise typer.Exit(code=1)

    display_id = uuid.uuid4().hex[:6]

    # Set up event system
    dispatcher = EventDispatcher()
    dispatcher.add_observer(StdoutObserver())
    dispatcher.add_observer(CxdbObserver(client, context_id))

    # Build backend and handler registry
    backend = _build_backend(config)
    registry = default_registry(backend=backend, config=config)

    # Run pipeline with SIGINT handling
    runner = PipelineRunner(graph, registry, dispatcher)

    original_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum: int, frame: object) -> None:
        typer.echo("\n[Pipeline] Pause requested — completing current node...")
        runner.request_pause()

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        outcome = runner.run(
            dot_file_path=dot_file_path,
            graph_hash=graph_hash,
            session_display_id=display_id,
        )
    finally:
        signal.signal(signal.SIGINT, original_handler)

    typer.echo(f"\nSession: {display_id} (CXDB context: {context_id})")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)
