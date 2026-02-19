from __future__ import annotations

from pathlib import Path

import typer

from orchestra.config.settings import load_config
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import BUNDLE_ID, publish_orchestra_types


def _find_repo_root() -> Path | None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
    return None


def _check_submodule() -> None:
    repo_root = _find_repo_root()
    if repo_root is None:
        return
    cxdb_dir = repo_root / "vendor" / "cxdb"
    if not cxdb_dir.exists() or not any(cxdb_dir.iterdir()):
        typer.echo(
            "CXDB submodule: NOT INITIALIZED\n\n"
            "Run:\n"
            "  git submodule update --init"
        )


def doctor() -> None:
    """Check CXDB connectivity and type registry status."""
    _check_submodule()

    config = load_config()
    typer.echo(f"CXDB URL: {config.cxdb.url}")

    client = CxdbClient(config.cxdb.url)
    try:
        result = client.health_check()
        typer.echo(f"CXDB health: OK ({result})")
    except CxdbConnectionError:
        typer.echo(
            "CXDB health: FAILED — cannot connect\n\n"
            "To start CXDB:\n"
            "  docker compose up -d"
        )
        raise typer.Exit(code=1)
    except CxdbError as e:
        typer.echo(f"CXDB health: FAILED — {e}")
        raise typer.Exit(code=1)

    try:
        publish_orchestra_types(client)
        typer.echo(f"Type bundle: OK ({BUNDLE_ID} registered)")
    except CxdbError as e:
        typer.echo(f"Type bundle: FAILED — {e}")
        raise typer.Exit(code=1)
    finally:
        client.close()
