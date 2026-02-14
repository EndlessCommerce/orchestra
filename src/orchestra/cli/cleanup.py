from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import typer

from orchestra.config.settings import load_config
from orchestra.engine.session import extract_session_info
from orchestra.events.dispatcher import EventDispatcher
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.workspace import git_ops

logger = logging.getLogger(__name__)


def cleanup(
    older_than: int = typer.Option(7, "--older-than", help="Remove branches older than N days"),
) -> None:
    """Remove stale session branches and orphaned worktrees."""
    config = load_config()

    if not config.workspace.repos:
        typer.echo("No workspace repos configured.")
        return

    # Connect to CXDB to identify active sessions
    client = CxdbClient(config.cxdb.url)
    try:
        client.health_check()
    except CxdbConnectionError:
        typer.echo(
            "Error: Cannot connect to CXDB (needed to identify active sessions).\n"
            "Run 'orchestra doctor' for setup instructions."
        )
        raise typer.Exit(code=1)
    except CxdbError as e:
        typer.echo(f"Error: CXDB health check failed: {e}")
        raise typer.Exit(code=1)

    # Get active session IDs (running or paused)
    active_session_ids = _get_active_session_ids(client)

    config_dir = config.config_dir or Path.cwd()

    removed_branches: list[str] = []
    removed_worktrees: list[str] = []
    preserved_branches: list[str] = []

    for repo_name, repo_config in config.workspace.repos.items():
        repo_path = Path(repo_config.path)
        if not repo_path.is_absolute():
            repo_path = (config_dir / repo_path).resolve()

        if not repo_path.exists():
            continue
        if not git_ops.is_git_repo(repo_path):
            continue

        prefix = repo_config.branch_prefix
        pattern = f"{prefix}*"

        branches = git_ops.list_branches(pattern, cwd=repo_path)

        for branch in branches:
            # Check if branch belongs to an active session
            session_id = _extract_session_id(branch, prefix)
            if session_id and session_id in active_session_ids:
                preserved_branches.append(f"{repo_name}:{branch}")
                continue

            # Check age
            try:
                date_str = git_ops.branch_date(branch, cwd=repo_path)
                if not _is_older_than_days(date_str, older_than):
                    preserved_branches.append(f"{repo_name}:{branch}")
                    continue
            except Exception:
                logger.warning("Failed to get date for branch %s in %s", branch, repo_name)
                continue

            # Remove stale branch
            try:
                git_ops.branch_delete(branch, cwd=repo_path)
                removed_branches.append(f"{repo_name}:{branch}")
            except Exception:
                logger.warning("Failed to delete branch %s in %s", branch, repo_name)

        # Clean orphaned worktrees
        worktree_base = repo_path / ".orchestra" / "worktrees"
        if worktree_base.exists():
            for session_dir in worktree_base.iterdir():
                if not session_dir.is_dir():
                    continue
                session_id = session_dir.name
                if session_id in active_session_ids:
                    continue
                # Orphaned worktree — remove
                for wt_dir in session_dir.iterdir():
                    if wt_dir.is_dir():
                        try:
                            git_ops.worktree_remove(wt_dir, cwd=repo_path)
                            removed_worktrees.append(f"{repo_name}:{wt_dir}")
                        except Exception:
                            logger.warning("Failed to remove worktree %s", wt_dir)
                # Remove the session directory if empty
                try:
                    session_dir.rmdir()
                except OSError:
                    pass

    # Report
    if removed_branches:
        typer.echo("Removed branches:")
        for b in removed_branches:
            typer.echo(f"  {b}")
    if removed_worktrees:
        typer.echo("Removed worktrees:")
        for w in removed_worktrees:
            typer.echo(f"  {w}")
    if preserved_branches:
        typer.echo(f"Preserved {len(preserved_branches)} active/recent branches.")

    if not removed_branches and not removed_worktrees:
        typer.echo("Nothing to clean up.")

    # Emit cleanup event
    dispatcher = EventDispatcher()
    dispatcher.emit(
        "CleanupCompleted",
        removed_branches=removed_branches,
        removed_worktrees=[str(w) for w in removed_worktrees],
        preserved_branches=preserved_branches,
    )

    client.close()


def _get_active_session_ids(client: CxdbClient) -> set[str]:
    """Return set of session display_ids that are running or paused."""
    active_ids: set[str] = set()
    try:
        contexts = client.list_contexts()
    except CxdbError:
        return active_ids

    for ctx in contexts:
        ctx_id = str(ctx.get("context_id", ctx.get("id", "")))
        if not ctx_id:
            continue
        try:
            turns = client.get_turns(ctx_id, limit=500)
        except CxdbError:
            continue

        info = extract_session_info(ctx_id, turns)
        if info.status in ("running", "paused") and info.display_id:
            active_ids.add(info.display_id)

    return active_ids


def _extract_session_id(branch: str, prefix: str) -> str:
    """Extract session ID from branch name like 'orchestra/pipeline-name/session-id'."""
    if not branch.startswith(prefix):
        return ""
    remainder = branch[len(prefix):]
    parts = remainder.split("/")
    if len(parts) >= 2:
        return parts[-1]
    return ""


def _is_older_than_days(date_str: str, days: int) -> bool:
    """Check if a git date string is older than N days."""
    try:
        # Git date format: 2024-01-15 10:30:45 -0500
        # Parse the date portion (ignore timezone for simplicity)
        date_part = date_str.rsplit(" ", 1)[0]  # Remove timezone
        dt = datetime.strptime(date_part, "%Y-%m-%d %H:%M:%S")
        dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - dt
        return age.days >= days
    except (ValueError, IndexError):
        return False
