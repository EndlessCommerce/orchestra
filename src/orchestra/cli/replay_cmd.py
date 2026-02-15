from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import typer

from orchestra.cli.backend_factory import build_backend
from orchestra.config.settings import load_config
from orchestra.engine.resume import (
    ResumeError,
    _extract_turn_data,
    _extract_type_id,
    load_graph_for_resume,
    verify_graph_hash,
)
from orchestra.engine.runner import PipelineRunner, _RunState
from orchestra.engine.turn_resume import TurnResumeInfo, restore_from_turn
from orchestra.events.dispatcher import EventDispatcher
from orchestra.events.observer import CxdbObserver, StdoutObserver
from orchestra.handlers.registry import default_registry
from orchestra.models.context import Context
from orchestra.models.outcome import OutcomeStatus
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import publish_orchestra_types


def _restore_from_checkpoint(
    turns: list[dict[str, Any]], checkpoint_id: str, context_id: str
) -> TurnResumeInfo:
    """Restore pipeline state from a specific checkpoint turn.

    Finds the checkpoint by turn_id, extracts next_node_id, context_snapshot,
    and workspace_snapshot.
    """
    if not turns:
        raise ResumeError("No turns found in session")

    # Find PipelineStarted for metadata
    pipeline_name = ""
    dot_file_path = ""
    graph_hash = ""
    for turn in turns:
        data = _extract_turn_data(turn)
        type_id = _extract_type_id(turn)
        if type_id == "dev.orchestra.PipelineLifecycle" and data.get("status") == "started":
            pipeline_name = data.get("pipeline_name", "")
            dot_file_path = data.get("dot_file_path", "")
            graph_hash = data.get("graph_hash", "")
            break

    # Find the target checkpoint
    checkpoint_data: dict[str, Any] | None = None
    for turn in turns:
        tid = str(turn.get("turn_id", ""))
        if tid == checkpoint_id and _extract_type_id(turn) == "dev.orchestra.Checkpoint":
            checkpoint_data = _extract_turn_data(turn)
            break

    if checkpoint_data is None:
        raise ResumeError(f"Checkpoint with turn_id={checkpoint_id} not found")

    next_node_id = checkpoint_data.get("next_node_id", "")
    if not next_node_id:
        raise ResumeError("Checkpoint has no next_node_id — pipeline may have terminated")

    # Restore _RunState from checkpoint
    ctx = Context()
    for key, value in checkpoint_data.get("context_snapshot", {}).items():
        ctx.set(key, value)

    visited_raw = checkpoint_data.get("visited_outcomes", {})
    visited_outcomes: dict[str, OutcomeStatus] = {}
    for node_id, status_str in visited_raw.items():
        visited_outcomes[node_id] = OutcomeStatus(status_str)

    state = _RunState(
        context=ctx,
        completed_nodes=list(checkpoint_data.get("completed_nodes", [])),
        visited_outcomes=visited_outcomes,
        retry_counters=dict(checkpoint_data.get("retry_counters", {})),
        reroute_count=int(checkpoint_data.get("reroute_count", 0)),
    )

    # Extract workspace snapshot for git restore
    workspace_snapshot = checkpoint_data.get("workspace_snapshot", {}) or {}

    # Build a git_sha from the first repo in the workspace snapshot
    git_sha = ""
    if workspace_snapshot:
        git_sha = next(iter(workspace_snapshot.values()), "")

    return TurnResumeInfo(
        state=state,
        next_node_id=next_node_id,
        turn_number=0,
        git_sha=git_sha,
        prior_messages=[],
        pipeline_name=pipeline_name,
        dot_file_path=dot_file_path,
        graph_hash=graph_hash,
        context_id=context_id,
    )


def replay(
    session_id: str,
    turn: str = typer.Option(None, "--turn", help="Agent turn ID to replay from"),
    checkpoint: str = typer.Option(None, "--checkpoint", help="Checkpoint turn ID to replay from"),
) -> None:
    """Replay a pipeline from a specific agent turn or checkpoint, forking the CXDB context."""
    if turn and checkpoint:
        typer.echo("Error: --turn and --checkpoint are mutually exclusive")
        raise typer.Exit(code=1)
    if not turn and not checkpoint:
        typer.echo("Error: must specify either --turn or --checkpoint")
        raise typer.Exit(code=1)

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

    # Restore from the specified turn or checkpoint
    fork_turn_id = turn or checkpoint
    try:
        if checkpoint:
            turn_info = _restore_from_checkpoint(turns, checkpoint, context_id)
        else:
            turn_info = restore_from_turn(turns, turn, context_id)
    except ResumeError as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)

    # Fork CXDB context at the specified turn (O(1) operation)
    try:
        fork_result = client.create_context(base_turn_id=fork_turn_id)
        new_context_id = str(fork_result.get("context_id", ""))
    except CxdbError as e:
        typer.echo(f"Error: Failed to fork CXDB context: {e}")
        raise typer.Exit(code=1)

    replay_source = f"checkpoint {checkpoint}" if checkpoint else f"turn {turn}"
    typer.echo(f"[Replay] Forked context at {replay_source} → new context {new_context_id}")

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

    # Restore git state
    if checkpoint and config.workspace.repos:
        # For checkpoint replay, use the full workspace snapshot (per-repo SHAs)
        workspace_snapshot = turn_info.state.context.snapshot().get("__workspace_snapshot__", {})
        # The checkpoint data already has workspace_snapshot — re-extract from turns
        for t in turns:
            tid = str(t.get("turn_id", ""))
            if tid == checkpoint and _extract_type_id(t) == "dev.orchestra.Checkpoint":
                cp_data = _extract_turn_data(t)
                ws_snap = cp_data.get("workspace_snapshot", {})
                if ws_snap:
                    from orchestra.workspace.restore import restore_git_state

                    config_dir = config.config_dir or dot_path.parent
                    restore_git_state(ws_snap, config.workspace.repos, config_dir)
                    shas = ", ".join(f"{k}={v[:8]}" for k, v in ws_snap.items())
                    typer.echo(f"[Replay] Workspace restored: {shas}")
                break
    elif turn_info.git_sha and config.workspace.repos:
        from orchestra.workspace.restore import restore_git_state

        config_dir = config.config_dir or dot_path.parent
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

    typer.echo(f"[Replay] Replaying from {replay_source} at node '{turn_info.next_node_id}'")

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
