from __future__ import annotations

import typer

from orchestra.config.settings import load_config
from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError
from orchestra.storage.type_bundle import BUNDLE_ID, publish_orchestra_types


def doctor() -> None:
    """Check CXDB connectivity and type registry status."""
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
            "  docker run -p 9009:9009 -p 9010:9010 cxdb/cxdb:latest"
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
