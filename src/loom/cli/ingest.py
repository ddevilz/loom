from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.core.graph import LoomGraph

console = Console()


@app.command()
def analyze(
    path: Path = typer.Argument(
        Path(), exists=True, file_okay=False, dir_okay=True
    ),
    db: Path | None = typer.Option(None, "--db", help="SQLite db path"),
) -> None:
    """Build or refresh the Loom graph for a repo."""
    from loom.ingest.pipeline import index_repo

    g = LoomGraph(db_path=db)
    result = asyncio.run(index_repo(path, g))
    console.print(
        f"[green]indexed {result.files_parsed} files, "
        f"{result.nodes_written} nodes, {result.edges_written} edges[/green]"
    )
    if result.errors:
        for err in result.errors:
            console.print(f"[yellow]warn: {err}[/yellow]")


@app.command()
def sync(
    path: Path = typer.Argument(
        Path(), exists=True, file_okay=False, dir_okay=True
    ),
    old_sha: str | None = typer.Option(None, "--old-sha"),
    new_sha: str | None = typer.Option(None, "--new-sha"),
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """Incremental sync of changed files (driven by SHA-256 hashes)."""
    from loom.ingest.incremental import sync_paths

    g = LoomGraph(db_path=db)
    r = asyncio.run(sync_paths(g, path, old_sha=old_sha, new_sha=new_sha))
    console.print(
        f"[green]synced {r.files_changed} files, "
        f"{r.nodes_written} nodes, {r.edges_written} edges[/green]"
    )


@app.command()
def serve(db: Path | None = typer.Option(None, "--db")) -> None:
    """Start the MCP stdio server."""
    from loom.mcp.server import build_server

    mcp = build_server(db_path=db)
    mcp.run()
