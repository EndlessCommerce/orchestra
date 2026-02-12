from __future__ import annotations

import typer

from orchestra.config.settings import load_config
from orchestra.engine.session import extract_session_info
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError


def status() -> None:
    """List pipeline sessions with status."""
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

    try:
        contexts = client.list_contexts()
    except CxdbError as e:
        typer.echo(f"Error: Failed to list contexts: {e}")
        raise typer.Exit(code=1)

    if not contexts:
        typer.echo("No sessions found.")
        return

    # Gather session info for each context
    sessions = []
    for ctx in contexts:
        ctx_id = str(ctx.get("context_id", ctx.get("id", "")))
        if not ctx_id:
            continue
        try:
            turns = client.get_turns(ctx_id, limit=500)
        except CxdbError:
            continue

        info = extract_session_info(ctx_id, turns)
        # Only show orchestra sessions (those with a PipelineStarted turn)
        if info.pipeline_name:
            sessions.append(info)

    if not sessions:
        typer.echo("No sessions found.")
        client.close()
        return

    # Print table
    typer.echo(f"{'ID':<10} {'Pipeline':<25} {'Status':<12} {'Turns':<6}")
    typer.echo("-" * 55)
    for s in sessions:
        display = s.display_id or s.context_id[:8]
        typer.echo(f"{display:<10} {s.pipeline_name:<25} {s.status:<12} {s.turn_count:<6}")

    client.close()
