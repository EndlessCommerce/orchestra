from __future__ import annotations

import signal
from pathlib import Path

import typer

from orchestra.cli.backend_factory import build_backend
from orchestra.config.settings import load_config
from orchestra.engine.resume import (
    ResumeError,
    load_graph_for_resume,
    restore_from_turns,
    verify_graph_hash,
)
from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.outcome import OutcomeStatus
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import publish_orchestra_types


def resume(session_id: str) -> None:
    """Resume a paused pipeline session."""
    config = load_config()
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

    # Resolve session_id — try as display_id first, then as context_id
    context_id = _resolve_session_id(client, session_id)
    if context_id is None:
        typer.echo(f"Error: session not found: {session_id}")
        raise typer.Exit(code=1)

    # Read turns and restore state
    try:
        turns = client.get_turns(context_id, limit=1000)
    except CxdbError as e:
        typer.echo(f"Error: Failed to read session: {e}")
        raise typer.Exit(code=1)

    try:
        resume_info = restore_from_turns(turns, context_id)
    except ResumeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Verify graph hasn't changed
    try:
        verify_graph_hash(resume_info.dot_file_path, resume_info.graph_hash)
    except ResumeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Load graph
    try:
        graph = load_graph_for_resume(resume_info.dot_file_path)
    except Exception as e:
        typer.echo(f"Error: Failed to load pipeline: {e}")
        raise typer.Exit(code=1)

    # Verify next node exists
    next_node = graph.get_node(resume_info.next_node_id)
    if next_node is None:
        typer.echo(f"Error: Next node '{resume_info.next_node_id}' not found in graph")
        raise typer.Exit(code=1)

    # Reload config from the pipeline's directory for correct backend/agent resolution
    dot_path = Path(resume_info.dot_file_path)
    config = load_config(start=dot_path.parent)

    # Publish type bundle (idempotent)
    try:
        publish_orchestra_types(client)
    except CxdbError as e:
        typer.echo(f"Error: Failed to publish type bundle: {e}")
        raise typer.Exit(code=1)

    # Set up event system — reuse the same CXDB context
    dispatcher = EventDispatcher()
    dispatcher.add_observer(StdoutObserver())
    dispatcher.add_observer(CxdbObserver(client, context_id))

    # Build interviewer
    from orchestra.interviewer.console import ConsoleInterviewer

    interviewer = ConsoleInterviewer()

    # Build backend and handler registry
    backend = build_backend(config)
    registry = default_registry(backend=backend, config=config, interviewer=interviewer)

    typer.echo(f"[Resume] Resuming session {session_id} from node '{resume_info.next_node_id}'")

    runner = PipelineRunner(graph, registry, dispatcher)

    original_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum: int, frame: object) -> None:
        typer.echo("\n[Pipeline] Pause requested — completing current node...")
        runner.request_pause()

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        outcome = runner.resume(
            state=resume_info.state,
            next_node=next_node,
            pipeline_name=resume_info.pipeline_name,
        )
    finally:
        signal.signal(signal.SIGINT, original_handler)

    typer.echo(f"\nSession: {session_id} (CXDB context: {context_id})")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)


def _resolve_session_id(client: CxdbClient, session_id: str) -> str | None:
    """Resolve a session_id (display_id or context_id) to a context_id."""
    # Try as context_id first
    try:
        turns = client.get_turns(session_id, limit=1)
        if turns:
            return session_id
    except CxdbError:
        pass

    # Try as display_id — search through contexts
    try:
        contexts = client.list_contexts()
    except CxdbError:
        return None

    for ctx in contexts:
        ctx_id = str(ctx.get("context_id", ctx.get("id", "")))
        if not ctx_id:
            continue
        try:
            # Use high limit to ensure PipelineStarted turn (first turn) is included
            # since CXDB returns turns from head backwards
            turns = client.get_turns(ctx_id, limit=500)
        except CxdbError:
            continue

        for turn in turns:
            data = turn.get("data", {})
            type_id = turn.get("type_id", "")
            if type_id == "dev.orchestra.PipelineLifecycle":
                if data.get("session_display_id") == session_id:
                    return ctx_id

    return None
