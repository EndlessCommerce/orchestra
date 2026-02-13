from __future__ import annotations

import signal
import uuid
from pathlib import Path

import blake3
import typer

from orchestra.cli.backend_factory import build_backend
from orchestra.config.settings import load_config
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
from orchestra.workspace.on_turn import build_on_turn_callback
from orchestra.workspace.session_branch import WorkspaceError


def run(
    pipeline: Path,
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve all human gates (no stdin required)"),
    single_line: bool = typer.Option(False, "--single-line", help="Use single-line input (Enter submits) instead of multiline"),
) -> None:
    """Execute a DOT pipeline."""
    if not pipeline.exists():
        typer.echo(f"Error: file not found: {pipeline}")
        raise typer.Exit(code=1)

    # Load config (search from the pipeline's directory first)
    config = load_config(start=pipeline.resolve().parent)

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

    # Build interviewer
    if auto_approve:
        from orchestra.interviewer.auto_approve import AutoApproveInterviewer

        interviewer = AutoApproveInterviewer()
    else:
        from orchestra.interviewer.console import ConsoleInterviewer

        interviewer = ConsoleInterviewer(multiline=not single_line)

    # Build backend
    backend = build_backend(config)

    # Set up workspace (if configured)
    workspace_manager = None
    if config.workspace.repos:
        if config.backend == "cli":
            typer.echo("Warning: Per-turn commits are not supported for CLI backend (deferred to Stage 6b)")
        else:
            try:
                from orchestra.workspace.commit_message import build_commit_message_generator
                from orchestra.workspace.workspace_manager import WorkspaceManager

                commit_gen = build_commit_message_generator(config)
                workspace_manager = WorkspaceManager(
                    config=config,
                    event_emitter=dispatcher,
                    commit_gen=commit_gen,
                )
                workspace_manager.setup_session(graph.name, display_id)
                dispatcher.add_observer(workspace_manager)
            except WorkspaceError as e:
                typer.echo(f"Error: Workspace setup failed: {e}")
                raise typer.Exit(code=1)

    # Build on_turn callback (always wired, even without workspace)
    on_turn = build_on_turn_callback(dispatcher, workspace_manager)

    # Build handler registry with on_turn
    registry = default_registry(
        backend=backend, config=config, interviewer=interviewer, on_turn=on_turn
    )

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
        if workspace_manager is not None:
            workspace_manager.teardown_session()

    typer.echo(f"\nSession: {display_id} (CXDB context: {context_id})")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)
