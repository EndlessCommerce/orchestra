from __future__ import annotations

from pathlib import Path

import typer

from orchestra.parser.parser import DotParseError, parse_dot
from orchestra.validation.validator import ValidationError, validate_or_raise


def compile(pipeline: Path) -> None:
    """Parse and validate a DOT pipeline file."""
    if not pipeline.exists():
        typer.echo(f"Error: file not found: {pipeline}")
        raise typer.Exit(code=1)

    source = pipeline.read_text()

    try:
        graph = parse_dot(source)
    except DotParseError as e:
        typer.echo(f"Parse error: {e}")
        raise typer.Exit(code=1)

    try:
        diagnostics = validate_or_raise(graph)
    except ValidationError as e:
        for d in e.diagnostics.diagnostics:
            prefix = d.severity.value
            location = f" (node: {d.node_id})" if d.node_id else ""
            if d.edge:
                location = f" (edge: {d.edge[0]} -> {d.edge[1]})"
            typer.echo(f"  {prefix}: [{d.rule}] {d.message}{location}")
            if d.suggestion:
                typer.echo(f"    Suggestion: {d.suggestion}")
        raise typer.Exit(code=1)

    for d in diagnostics.warnings:
        typer.echo(f"  WARNING: [{d.rule}] {d.message}")
        if d.suggestion:
            typer.echo(f"    Suggestion: {d.suggestion}")

    typer.echo(f"Pipeline: {graph.name}")
    typer.echo(f"  Goal: {graph.goal or '(none)'}")
    typer.echo(f"  Nodes: {len(graph.nodes)}")
    typer.echo(f"  Edges: {len(graph.edges)}")

    for node in graph.nodes.values():
        typer.echo(f"    {node.id} [{node.shape}] — {node.label}")
