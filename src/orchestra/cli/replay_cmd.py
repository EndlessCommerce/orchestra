from __future__ import annotations

import signal
from pathlib import Path

import typer

from orchestra.cli.backend_factory import build_backend
from orchestra.config.settings import load_config
from orchestra.engine.resume import (
    ResumeError,
    load_graph_for_resume,
    verify_graph_hash,
)
from orchestra.engine.runner import PipelineRunner
from orchestra.engine.turn_resume import restore_from_turn
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.outcome import OutcomeStatus
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import publish_orchestra_types


def replay(
    session_id: str,
    turn: str = typer.Option(..., "--turn", help="Agent turn ID to replay from"),
) -> None:
    """Replay a pipeline from a specific agent turn, forking the CXDB context."""
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

    # Resolve session_id
    from orchestra.cli.resume_cmd import _resolve_session_id

    context_id = _resolve_session_id(client, session_id)
    if context_id is None:
        typer.echo(f"Error: session not found: {session_id}")
        raise typer.Exit(code=1)

    # Read turns
    try:
        turns = client.get_turns(context_id, limit=1000)
    except CxdbError as e:
        typer.echo(f"Error: Failed to read session: {e}")
        raise typer.Exit(code=1)

    # Restore from the specified turn
    try:
        turn_info = restore_from_turn(turns, turn, context_id)
    except ResumeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Fork CXDB context at the specified turn (O(1) operation)
    try:
        fork_result = client.create_context(base_turn_id=turn)
        new_context_id = str(fork_result.get("context_id", ""))
    except CxdbError as e:
        typer.echo(f"Error: Failed to fork CXDB context: {e}")
        raise typer.Exit(code=1)

    typer.echo(f"[Replay] Forked context at turn {turn} → new context {new_context_id}")

    # Verify graph hasn't changed
    try:
        verify_graph_hash(turn_info.dot_file_path, turn_info.graph_hash)
    except ResumeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Load graph
    try:
        graph = load_graph_for_resume(turn_info.dot_file_path)
    except Exception as e:
        typer.echo(f"Error: Failed to load pipeline: {e}")
        raise typer.Exit(code=1)

    # Verify next node exists
    next_node = graph.get_node(turn_info.next_node_id)
    if next_node is None:
        typer.echo(f"Error: Next node '{turn_info.next_node_id}' not found in graph")
        raise typer.Exit(code=1)

    # Reload config from pipeline directory
    dot_path = Path(turn_info.dot_file_path)
    config = load_config(start=dot_path.parent)

    # Restore git state to the turn's SHA
    if turn_info.git_sha and config.workspace.repos:
        from orchestra.workspace.restore import restore_git_state

        config_dir = config.config_dir or dot_path.parent
        # Use first repo for single-repo case; for multi-repo, the SHA applies per-repo
        for repo_name in config.workspace.repos:
            restore_git_state(
                {repo_name: turn_info.git_sha},
                config.workspace.repos,
                config_dir,
            )
        typer.echo(f"[Replay] Git state restored to {turn_info.git_sha[:8]}")

    # Publish type bundle
    try:
        publish_orchestra_types(client)
    except CxdbError as e:
        typer.echo(f"Error: Failed to publish type bundle: {e}")
        raise typer.Exit(code=1)

    # Set up event system pointing at the FORKED context
    dispatcher = EventDispatcher()
    dispatcher.add_observer(StdoutObserver())
    dispatcher.add_observer(CxdbObserver(client, new_context_id))

    # Build interviewer
    from orchestra.interviewer.console import ConsoleInterviewer

    interviewer = ConsoleInterviewer()

    # Set up workspace (if configured)
    workspace_manager = None
    on_turn = None
    if config.workspace.repos:
        try:
            from orchestra.workspace.commit_message import build_commit_message_generator
            from orchestra.workspace.on_turn import build_on_turn_callback
            from orchestra.workspace.workspace_manager import WorkspaceManager

            commit_gen = build_commit_message_generator(config)
            workspace_manager = WorkspaceManager(
                config=config,
                event_emitter=dispatcher,
                commit_gen=commit_gen,
            )
            workspace_manager.setup_session(turn_info.pipeline_name, session_id)
            dispatcher.add_observer(workspace_manager)
            on_turn = build_on_turn_callback(dispatcher, workspace_manager)
        except Exception as e:
            typer.echo(f"Warning: Workspace setup failed during replay: {e}")
            workspace_manager = None

    # Build backend and handler registry
    backend = build_backend(config)
    registry = default_registry(
        backend=backend, config=config, interviewer=interviewer,
        on_turn=on_turn, workspace_manager=workspace_manager,
    )

    typer.echo(f"[Replay] Replaying from turn {turn} at node '{turn_info.next_node_id}'")

    runner = PipelineRunner(graph, registry, dispatcher, workspace_manager=workspace_manager)

    original_handler = signal.getsignal(signal.SIGINT)

    def _sigint_handler(signum: int, frame: object) -> None:
        typer.echo("\n[Pipeline] Pause requested — completing current node...")
        runner.request_pause()

    signal.signal(signal.SIGINT, _sigint_handler)
    try:
        outcome = runner.resume(
            state=turn_info.state,
            next_node=next_node,
            pipeline_name=turn_info.pipeline_name,
        )
    finally:
        signal.signal(signal.SIGINT, original_handler)
        if workspace_manager is not None:
            workspace_manager.teardown_session()

    typer.echo(f"\nReplay session: {session_id} → forked context: {new_context_id}")

    client.close()

    if outcome.status != OutcomeStatus.SUCCESS:
        raise typer.Exit(code=1)
