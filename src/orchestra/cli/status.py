from __future__ import annotations

import json
from typing import Any

import typer

from orchestra.config.settings import load_config
from orchestra.engine.session import extract_session_info
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError


def _aggregate_detail(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate per-node detail from CXDB turns.

    Groups AgentTurn turns by node_id, sums token usage, counts tool invocations,
    and extracts timing from NodeExecution turns.

    Returns a list of dicts: [{node_id, status, tokens_in, tokens_out, tools, duration_ms}]
    """
    node_data: dict[str, dict[str, Any]] = {}

    for turn in turns:
        type_id = turn.get("type_id", "")
        data = turn.get("data", {})

        if type_id == "dev.orchestra.AgentTurn":
            node_id = data.get("node_id", "unknown")
            entry = node_data.setdefault(node_id, {
                "node_id": node_id,
                "status": "",
                "tokens_in": 0,
                "tokens_out": 0,
                "tools": 0,
                "duration_ms": 0,
            })
            token_usage = data.get("token_usage", {})
            if isinstance(token_usage, dict):
                entry["tokens_in"] += token_usage.get("input", 0)
                entry["tokens_out"] += token_usage.get("output", 0)

            tool_calls_raw = data.get("tool_calls", "")
            if tool_calls_raw:
                try:
                    calls = json.loads(tool_calls_raw) if isinstance(tool_calls_raw, str) else tool_calls_raw
                    if isinstance(calls, list):
                        entry["tools"] += len(calls)
                except (json.JSONDecodeError, TypeError):
                    pass

        elif type_id == "dev.orchestra.NodeExecution":
            node_id = data.get("node_id", "unknown")
            entry = node_data.setdefault(node_id, {
                "node_id": node_id,
                "status": "",
                "tokens_in": 0,
                "tokens_out": 0,
                "tools": 0,
                "duration_ms": 0,
            })
            status = data.get("status", "")
            if status:
                entry["status"] = status
            duration = data.get("duration_ms", 0)
            if duration:
                entry["duration_ms"] += int(duration)

    return list(node_data.values())


def _show_detail(client: CxdbClient, context_id: str) -> None:
    """Show detailed per-node information for a session."""
    try:
        turns = client.get_turns(context_id, limit=2000)
    except CxdbError as e:
        typer.echo(f"Error: Failed to read session: {e}")
        raise typer.Exit(code=1)

    info = extract_session_info(context_id, turns)
    display = info.display_id or info.context_id[:8]
    typer.echo(f"Session: {display} ({info.pipeline_name}) — {info.status}")
    typer.echo("")

    details = _aggregate_detail(turns)
    if not details:
        typer.echo("No node execution data found.")
        return

    typer.echo(f"{'Node':<20} {'Status':<12} {'Tokens (In/Out)':<20} {'Tools':<8} {'Duration':<10}")
    typer.echo("-" * 72)

    for d in details:
        tokens_str = f"{d['tokens_in']}/{d['tokens_out']}"
        duration_str = f"{d['duration_ms']}ms" if d['duration_ms'] else "-"
        typer.echo(
            f"{d['node_id']:<20} {d['status']:<12} {tokens_str:<20} {d['tools']:<8} {duration_str:<10}"
        )


def status(
    session_id: str = typer.Argument(None, help="Session ID to show detail for"),
    detail: bool = typer.Option(False, "--detail", help="Show per-node detail for a session"),
) -> None:
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

    if detail:
        if session_id:
            from orchestra.cli.resume_cmd import _resolve_session_id

            context_id = _resolve_session_id(client, session_id)
            if context_id is None:
                typer.echo(f"Error: session not found: {session_id}")
                raise typer.Exit(code=1)
        else:
            # Find most recent session
            try:
                contexts = client.list_contexts()
            except CxdbError as e:
                typer.echo(f"Error: Failed to list contexts: {e}")
                raise typer.Exit(code=1)

            context_id = _find_most_recent_session(client, contexts)
            if context_id is None:
                typer.echo("No sessions found.")
                client.close()
                return

        _show_detail(client, context_id)
        client.close()
        return

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


def _find_most_recent_session(
    client: CxdbClient, contexts: list[dict[str, Any]]
) -> str | None:
    """Find the most recent Orchestra session context ID."""
    for ctx in reversed(contexts):
        ctx_id = str(ctx.get("context_id", ctx.get("id", "")))
        if not ctx_id:
            continue
        try:
            turns = client.get_turns(ctx_id, limit=10)
        except CxdbError:
            continue
        info = extract_session_info(ctx_id, turns)
        if info.pipeline_name:
            return ctx_id
    return None
