from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.core.graph import LoomGraph

console = Console()


@app.command()
def communities(
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """Run Louvain community detection and print cluster count."""
    from loom.analysis.communities import compute_communities

    g = LoomGraph(db_path=db)
    n = asyncio.run(compute_communities(g))
    console.print(f"[green]{n} communities computed[/green]")


@app.command(name="dead-code")
def dead_code(
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """Mark functions with no incoming CALLS as dead code."""
    from loom.analysis.dead_code import mark_dead_code

    g = LoomGraph(db_path=db)
    n = asyncio.run(mark_dead_code(g))
    console.print(f"[green]{n} dead-code nodes marked[/green]")
