from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter

import typer
from rich.console import Console
from rich.table import Table


app = typer.Typer(add_completion=False)


@app.command()
def analyze(
    path: str = typer.Argument(..., help="Path to a repo or file"),
    docs: str | None = typer.Option(None, "--docs"),
    graph_name: str = typer.Option("loom", "--graph-name"),
    exclude_tests: bool = typer.Option(False, "--exclude-tests"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    from loom.core import LoomGraph
    from loom.ingest.pipeline import index_repo

    console = Console()
    target = str(Path(path))
    console.print(f"Analyzing {target}...")

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)
        res = await index_repo(
            target,
            graph,
            force=force,
            exclude_tests=exclude_tests,
            docs_path=docs,
        )

        by_kind_rows = await graph.query(
            "MATCH (n) RETURN n.kind AS kind, count(n) AS c ORDER BY c DESC LIMIT 8"
        )

        table = Table(show_header=False)
        table.add_row("file_count", str(res.file_count))
        table.add_row("files_skipped", str(res.files_skipped))
        table.add_row("files_updated", str(res.files_updated))
        table.add_row("files_added", str(res.files_added))
        table.add_row("files_deleted", str(res.files_deleted))
        table.add_row("nodes", str(res.node_count))
        table.add_row("edges", str(res.edge_count))
        table.add_row("errors", str(res.error_count))
        table.add_row("seconds", f"{res.duration_ms / 1000.0:.2f}")
        console.print(table)

        if by_kind_rows:
            kinds = Table(title="Top node kinds", show_header=True, header_style="bold")
            kinds.add_column("kind")
            kinds.add_column("count", justify="right")
            for row in by_kind_rows:
                kinds.add_row(str(row.get("kind")), str(row.get("c")))
            console.print(kinds)

    asyncio.run(_run())


@app.command()
def calls(
    target: str | None = typer.Option(None, "--target", help="Node id or plain name to inspect."),
    graph_name: str = typer.Option("loom", "--graph-name"),
    kind: str | None = typer.Option(None, "--kind", help="Optional NodeKind when target is a plain name."),
    direction: str = typer.Option(
        "callees",
        "--direction",
        help="callees|callers|both|dump",
    ),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    from loom.core import LoomGraph
    from loom.core.node import NodeKind

    console = Console()

    async def _resolve_node_id(graph: LoomGraph, node: str) -> str | None:
        if ":" in node:
            return node

        label_clause = ":Node"
        if kind is not None:
            try:
                k = NodeKind(kind)
            except Exception:
                console.print(f"Invalid --kind: {kind}")
                raise typer.Exit(code=1)
            label_clause = f":`{k.name.title()}`"

        rows = await graph.query(
            f"MATCH (n{label_clause} {{name: $name}}) RETURN n.id AS id LIMIT 1",
            {"name": node},
        )
        if not rows:
            return None
        return rows[0].get("id")

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if direction == "dump":
            rows = await graph.query(
                """
MATCH (a)-[r:CALLS]->(b)
RETURN a.name AS from_name, a.path AS from_path,
       b.name AS to_name, b.path AS to_path,
       r.confidence AS confidence
LIMIT $limit
""",
                {"limit": limit},
            )
            table = Table(show_header=True, header_style="bold")
            table.add_column("from")
            table.add_column("to")
            table.add_column("confidence", justify="right")
            for row in rows:
                f = f"{row.get('from_name')} ({row.get('from_path')})"
                t = f"{row.get('to_name')} ({row.get('to_path')})"
                table.add_row(f, t, str(row.get("confidence")))
            console.print(table if rows else "(none)")
            return

        if not target:
            console.print("--target is required unless --direction dump")
            raise typer.Exit(code=1)

        node_id = await _resolve_node_id(graph, target)
        if node_id is None:
            console.print("Target not found")
            raise typer.Exit(code=1)

        if direction in {"callees", "both"}:
            rows = await graph.query(
                """
MATCH (a {id: $id})-[r:CALLS]->(b)
RETURN b.kind AS kind, b.name AS name, b.path AS path, r.confidence AS confidence
ORDER BY confidence DESC
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            console.print("=== callees ===")
            if rows:
                table = Table(show_header=True, header_style="bold")
                table.add_column("kind")
                table.add_column("name")
                table.add_column("path")
                table.add_column("confidence", justify="right")
                for row in rows:
                    table.add_row(
                        str(row.get("kind")),
                        str(row.get("name")),
                        str(row.get("path")),
                        str(row.get("confidence")),
                    )
                console.print(table)
            else:
                console.print("(none)")

        if direction in {"callers", "both"}:
            rows = await graph.query(
                """
MATCH (a)-[r:CALLS]->(b {id: $id})
RETURN a.kind AS kind, a.name AS name, a.path AS path, r.confidence AS confidence
ORDER BY confidence DESC
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            console.print("=== callers ===")
            if rows:
                table = Table(show_header=True, header_style="bold")
                table.add_column("kind")
                table.add_column("name")
                table.add_column("path")
                table.add_column("confidence", justify="right")
                for row in rows:
                    table.add_row(
                        str(row.get("kind")),
                        str(row.get("name")),
                        str(row.get("path")),
                        str(row.get("confidence")),
                    )
                console.print(table)
            else:
                console.print("(none)")

    asyncio.run(_run())


@app.command()
def entrypoints(
    graph_name: str = typer.Option("loom", "--graph-name"),
    limit: int = typer.Option(30, "--limit"),
) -> None:
    from loom.core import LoomGraph

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        q1 = (
            "MATCH (n) "
            "WHERE toLower(n.name) IN ['main','start','run','bootstrap','init','app','server'] "
            "RETURN n.kind AS kind, n.name AS name, n.path AS path, n.id AS id "
            "LIMIT $limit"
        )
        r1 = await graph.query(q1, {"limit": limit})

        q2 = (
            "MATCH (n) "
            "WHERE NOT ( ()-[:calls]->(n) ) "
            "WITH n "
            "MATCH (n)-[:calls]->(m) "
            "RETURN n.kind AS kind, n.name AS name, n.path AS path, count(m) AS out_calls "
            "ORDER BY out_calls DESC "
            "LIMIT $limit"
        )
        r2 = await graph.query(q2, {"limit": limit})

        q3 = (
            "MATCH ()-[r]->() "
            "RETURN type(r) AS t, count(r) AS c "
            "ORDER BY c DESC "
            "LIMIT 20"
        )
        r3 = await graph.query(q3)

        console.print("=== name-based candidates ===")
        if r1:
            t = Table(show_header=True, header_style="bold")
            t.add_column("kind")
            t.add_column("name")
            t.add_column("path")
            for row in r1:
                t.add_row(str(row.get("kind")), str(row.get("name")), str(row.get("path")))
            console.print(t)
        else:
            console.print("(none)")

        console.print("=== call roots (no incoming CALLS) ===")
        if r2:
            t = Table(show_header=True, header_style="bold")
            t.add_column("out_calls", justify="right")
            t.add_column("kind")
            t.add_column("name")
            t.add_column("path")
            for row in r2:
                t.add_row(
                    str(row.get("out_calls")),
                    str(row.get("kind")),
                    str(row.get("name")),
                    str(row.get("path")),
                )
            console.print(t)
        else:
            console.print("(none)")

        console.print("=== relationship types ===")
        if r3:
            t = Table(show_header=True, header_style="bold")
            t.add_column("type")
            t.add_column("count", justify="right")
            for row in r3:
                t.add_row(str(row.get("t")), str(row.get("c")))
            console.print(t)
        else:
            console.print("(none)")

    asyncio.run(_run())


@app.command()
def sync(
    old_sha: str = typer.Option(..., "--old-sha"),
    new_sha: str = typer.Option(..., "--new-sha"),
    graph_name: str = typer.Option("loom", "--graph-name"),
    repo_path: str = typer.Option(".", "--repo-path"),
) -> None:
    from loom.core import LoomGraph
    from loom.ingest.git import get_changed_files
    from loom.ingest.incremental import sync_commits

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        try:
            changes = await get_changed_files(repo_path, old_sha, new_sha)
        except Exception as e:
            console.print(f"Invalid git refs or repo: {e}")
            raise typer.Exit(code=1)

        console.print(f"Syncing {old_sha}..{new_sha} ({len(changes)} files changed)")
        for ch in changes[:50]:
            if ch.status == "R" and ch.old_path:
                console.print(f"  {ch.status} {ch.old_path} -> {ch.path}")
            else:
                console.print(f"  {ch.status} {ch.path}")

        res = await sync_commits(repo_path, old_sha, new_sha, graph)

        table = Table(show_header=False)
        table.add_row("files_updated", str(res.files_updated))
        table.add_row("files_added", str(res.files_added))
        table.add_row("files_deleted", str(res.files_deleted))
        table.add_row("nodes", str(res.node_count))
        table.add_row("edges", str(res.edge_count))
        table.add_row("errors", str(res.error_count))
        table.add_row("seconds", f"{res.duration_ms / 1000.0:.2f}")
        console.print(table)

        if res.error_count:
            console.print("Review errors in output.")

    asyncio.run(_run())


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Development mode (placeholder)."),
) -> None:
    if dev:
        Console().print("loom (dev): package import OK")
        raise typer.Exit(code=0)
    if ctx.invoked_subcommand is None:
        raise typer.Exit(code=0)


def main() -> int:
    try:
        app(prog_name="loom")
        return 0
    except SystemExit as e:
        code = e.code
        return int(code) if isinstance(code, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
