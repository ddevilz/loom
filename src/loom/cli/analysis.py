from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from loom.analysis.communities import compute_communities
from loom.analysis.dead_code import mark_dead_code
from loom.cli._app import app

console = Console()


@app.command()
def communities(ctx: typer.Context) -> None:
    """Run Louvain community detection and print cluster count."""
    db = ctx.obj["db"]
    n = asyncio.run(compute_communities(db))
    console.print(f"[green]{n} communities computed[/green]")


@app.command(name="dead-code")
def dead_code(ctx: typer.Context) -> None:
    """Mark functions with no incoming CALLS as dead code."""
    db = ctx.obj["db"]
    n = asyncio.run(mark_dead_code(db))
    console.print(f"[green]{n} dead-code nodes marked[/green]")
