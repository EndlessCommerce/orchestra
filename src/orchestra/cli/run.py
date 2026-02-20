from __future__ import annotations

import signal
import uuid
from pathlib import Path
from typing import Optional

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


def _parse_vars(raw: list[str]) -> dict[str, str]:
    """Parse ``key=value`` pairs from CLI arguments.

    Raises :class:`typer.BadParameter` on malformed input.
    """
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise typer.BadParameter(f"Expected key=value, got: {item!r}")
        key, _, value = item.partition("=")
        if not key:
            raise typer.BadParameter(f"Empty key in: {item!r}")
        if not value:
            raise typer.BadParameter(f"Empty value in: {item!r}")
        result[key] = value
    return result


def run(
    pipeline: Path,
    vars: Optional[list[str]] = typer.Argument(None, help="Variables as key=value pairs"),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Auto-approve all human gates (no stdin required)"),
    multi_line: bool = typer.Option(False, "--multi-line", help="Use multiline input (Alt+Enter submits) instead of single-line"),
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

        interviewer = ConsoleInterviewer(multiline=multi_line)

    # Set up workspace (if configured) — must happen before backend so tools are available
    workspace_manager = None
    repo_contexts: dict = {}
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
                repo_contexts = workspace_manager.setup_session(graph.name, display_id)
                dispatcher.add_observer(workspace_manager)

                # Register PushObserver for on_checkpoint push (after CxdbObserver)
                from orchestra.events.observer import PushObserver
                dispatcher.add_observer(PushObserver(workspace_manager))
            except WorkspaceError as e:
                typer.echo(f"Error: Workspace setup failed: {e}")
                raise typer.Exit(code=1)

    # Create repo tools (if workspace has repos)
    repo_tools = None
    write_tracker = None
    if repo_contexts:
        from orchestra.backends.write_tracker import WriteTracker
        from orchestra.workspace.repo_tools import create_repo_tools, create_workspace_tools

        write_tracker = WriteTracker()
        repo_tools = create_repo_tools(repo_contexts, write_tracker)

        # Add custom tools from workspace.tools config
        if config.workspace.tools:
            repo_tools.extend(create_workspace_tools(
                config.workspace.tools, repo_contexts,
            ))

    # Build backend
    backend = build_backend(config, tools=repo_tools, write_tracker=write_tracker)

    # Build on_turn callback (always wired, even without workspace)
    on_turn = build_on_turn_callback(dispatcher, workspace_manager)

    # Build handler registry with on_turn and workspace_manager
    registry = default_registry(
        backend=backend, config=config, interviewer=interviewer, on_turn=on_turn,
        workspace_manager=workspace_manager,
    )

    # Build initial context from CLI variables
    from orchestra.models.context import Context

    initial_context = Context()
    if vars:
        parsed = _parse_vars(vars)
        for key, value in parsed.items():
            initial_context.set(key, value)

    # Run pipeline with SIGINT handling
    runner = PipelineRunner(graph, registry, dispatcher, workspace_manager=workspace_manager)

    original_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum: int, frame: object) -> None:
        typer.echo("\n[Pipeline] Pause requested — completing current node...")
        runner.request_pause()

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        outcome = runner.run(
            context=initial_context,
            dot_file_path=dot_file_path,
            graph_hash=graph_hash,
            session_display_id=display_id,
        )

        # Push on completion (before teardown restores original branches)
        if workspace_manager is not None and outcome.status == OutcomeStatus.SUCCESS:
            workspace_manager.push_session_branches("on_completion")
    finally:
        signal.signal(signal.SIGINT, original_handler)
        if workspace_manager is not None:
            workspace_manager.teardown_session()

    typer.echo(f"\nSession: {display_id} (CXDB context: {context_id})")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)
