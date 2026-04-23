from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from loom.cli._app import app
from loom.core.edge import EdgeType
from loom.core.graph import LoomGraph
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.node_lookup import resolve_node_id
from loom.query.search import search as search_nodes

console = Console()


def _resolve(g: LoomGraph, name_or_id: str) -> str:
    if ":" in name_or_id:
        return name_or_id
    return asyncio.run(resolve_node_id(g, target=name_or_id)) or name_or_id


@app.command(name="blast-radius")
def blast_radius(
    target: str,
    depth: int = typer.Option(3, "--depth", "-d"),
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """Show transitive callers of a function."""
    g = LoomGraph(db_path=db)
    nid = _resolve(g, target)
    payload = asyncio.run(build_blast_radius_payload(g, node_id=nid, depth=depth))
    console.print_json(data=payload)


@app.command()
def callers(
    target: str,
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """List direct callers of a function (one-hop incoming CALLS)."""
    g = LoomGraph(db_path=db)
    nid = _resolve(g, target)
    rows = asyncio.run(
        g.neighbors(nid, depth=1, edge_types=[EdgeType.CALLS], direction="in")
    )
    t = Table("id", "name", "path")
    for n in rows:
        t.add_row(n.id, n.name, n.path)
    console.print(t)


@app.command()
def callees(
    target: str,
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """List functions this target calls (one-hop outgoing CALLS)."""
    g = LoomGraph(db_path=db)
    nid = _resolve(g, target)
    rows = asyncio.run(
        g.neighbors(nid, depth=1, edge_types=[EdgeType.CALLS], direction="out")
    )
    t = Table("id", "name", "path")
    for n in rows:
        t.add_row(n.id, n.name, n.path)
    console.print(t)


@app.command()
def query(
    q: str,
    limit: int = typer.Option(10, "--limit", "-n"),
    db: Path | None = typer.Option(None, "--db"),
) -> None:
    """FTS5 / name search across nodes."""
    g = LoomGraph(db_path=db)
    results = asyncio.run(search_nodes(q, g, limit=limit))
    t = Table("id", "name", "path", "kind")
    for r in results:
        t.add_row(r.node.id, r.node.name, r.node.path, r.node.kind.value)
    console.print(t)


@app.command()
def stats(db: Path | None = typer.Option(None, "--db")) -> None:
    """Show graph statistics."""
    g = LoomGraph(db_path=db)
    s = asyncio.run(g.stats())
    console.print_json(data=s)
