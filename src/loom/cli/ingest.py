from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.ingest.pipeline import index_repo
from loom.ingest.incremental import sync_paths
from loom.mcp.server import build_server

console = Console()


@app.command()
def analyze(
    ctx: typer.Context,
    path: Path = typer.Argument(
        Path(), exists=True, file_okay=False, dir_okay=True
    ),
) -> None:
    """Build or refresh the Loom graph for a repo."""
    db = ctx.obj["db"]
    result = asyncio.run(index_repo(path, db))
    console.print(
        f"[green]indexed {result.files_parsed} files, "
        f"{result.nodes_written} nodes, {result.edges_written} edges[/green]"
    )
    if result.errors:
        for err in result.errors:
            console.print(f"[yellow]warn: {err}[/yellow]")


@app.command()
def sync(
    ctx: typer.Context,
    path: Path = typer.Argument(
        Path(), exists=True, file_okay=False, dir_okay=True
    ),
    old_sha: str | None = typer.Option(None, "--old-sha"),
    new_sha: str | None = typer.Option(None, "--new-sha"),
) -> None:
    """Incremental sync of changed files (driven by SHA-256 hashes)."""
    db = ctx.obj["db"]
    r = asyncio.run(sync_paths(db, path, old_sha=old_sha, new_sha=new_sha))
    console.print(
        f"[green]synced {r.files_changed} files, "
        f"{r.nodes_written} nodes, {r.edges_written} edges[/green]"
    )


@app.command()
def serve(ctx: typer.Context) -> None:
    """Start the MCP stdio server."""
    db = ctx.obj["db"]
    mcp = build_server(db=db)
    mcp.run()


@app.command()
def context(
    ctx: typer.Context,
    module: str | None = typer.Option(None, "--module", "-m", help="Zoom into one module"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
) -> None:
    """Print compressed codebase overview for agent session startup (~200 tokens)."""
    import json as _json
    from loom.query.primer import build_primer

    db = ctx.obj["db"]
    result = asyncio.run(build_primer(db, module=module, as_json=json_output))

    if json_output:
        console.print(_json.dumps(result, indent=2, default=str))
    else:
        console.print(result)
