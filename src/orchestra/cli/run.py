from __future__ import annotations

import uuid
from pathlib import Path

import typer

from orchestra.config.settings import load_config
from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.outcome import OutcomeStatus
from orchestra.parser.parser import DotParseError, parse_dot
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import publish_orchestra_types
from orchestra.transforms.variable_expansion import expand_variables
from orchestra.validation.validator import ValidationError, validate_or_raise


def run(pipeline: Path) -> None:
    """Execute a DOT pipeline in simulation mode."""
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

    # Set up handlers
    registry = default_registry()

    # Run pipeline
    runner = PipelineRunner(graph, registry, dispatcher)
    outcome = runner.run()

    typer.echo(f"\nSession: {display_id} (CXDB context: {context_id})")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)
