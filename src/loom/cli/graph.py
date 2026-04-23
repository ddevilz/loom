from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from loom.cli._app import app
from loom.core.context import DB
from loom.core.edge import EdgeType
from loom.query import traversal
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.node_lookup import resolve_node_id
from loom.query.search import search as search_nodes
from loom.store import nodes as node_store

console = Console()


def _resolve(db: DB, name_or_id: str) -> str:
    if ":" in name_or_id:
        return name_or_id
    return asyncio.run(resolve_node_id(db, target=name_or_id)) or name_or_id


@app.command(name="blast-radius")
def blast_radius(
    ctx: typer.Context,
    target: str,
    depth: int = typer.Option(3, "--depth", "-d"),
) -> None:
    """Show transitive callers of a function."""
    db = ctx.obj["db"]
    nid = _resolve(db, target)
    payload = asyncio.run(build_blast_radius_payload(db, node_id=nid, depth=depth))
    console.print_json(data=payload)


@app.command()
def callers(ctx: typer.Context, target: str) -> None:
    """List direct callers of a function (one-hop incoming CALLS)."""
    db = ctx.obj["db"]
    nid = _resolve(db, target)
    rows = asyncio.run(
        traversal.neighbors(db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="in")
    )
    t = Table("id", "name", "path")
    for n in rows:
        t.add_row(n.id, n.name, n.path)
    console.print(t)


@app.command()
def callees(ctx: typer.Context, target: str) -> None:
    """List functions this target calls (one-hop outgoing CALLS)."""
    db = ctx.obj["db"]
    nid = _resolve(db, target)
    rows = asyncio.run(
        traversal.neighbors(db, nid, depth=1, edge_types=[EdgeType.CALLS], direction="out")
    )
    t = Table("id", "name", "path")
    for n in rows:
        t.add_row(n.id, n.name, n.path)
    console.print(t)


@app.command()
def query(
    ctx: typer.Context,
    q: str,
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """FTS5 / name search across nodes."""
    db = ctx.obj["db"]
    results = asyncio.run(search_nodes(q, db, limit=limit))
    t = Table("id", "name", "path", "kind")
    for r in results:
        t.add_row(r.node.id, r.node.name, r.node.path, r.node.kind.value)
    console.print(t)


@app.command()
def stats(ctx: typer.Context) -> None:
    """Show graph statistics."""
    db = ctx.obj["db"]
    s = asyncio.run(traversal.stats(db))
    console.print_json(data=s)


@app.command()
def summaries(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Show nodes with agent-written summaries (most recently updated first)."""
    db = ctx.obj["db"]
    rows = asyncio.run(node_store.get_summaries(db, limit=limit))
    t = Table("name", "path", "summary")
    for r in rows:
        t.add_row(r["name"], r["path"], (r["summary"] or "")[:72])
    console.print(t)
