from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from loom.config import LOOM_DB_HOST, LOOM_DB_PORT


app = typer.Typer(add_completion=False)

_NONE_TEXT = "(none)"


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    table = Table(show_header=False)
    for key, value in rows:
        table.add_row(key, value)
    return table


def _render_table(
    *,
    columns: list[tuple[str, str | None]],
    rows: list[dict[str, object]],
    title: str | None = None,
) -> Table:
    table = Table(show_header=True, header_style="bold", title=title)
    for name, justify in columns:
        if justify is None:
            table.add_column(name)
        else:
            table.add_column(name, justify=justify)
    for row in rows:
        table.add_row(*[str(row.get(name)) for name, _ in columns])
    return table


def _print_table_or_none(
    console: Console,
    *,
    heading: str | None,
    columns: list[tuple[str, str | None]],
    rows: list[dict[str, object]],
) -> None:
    if heading is not None:
        console.print(heading)
    if rows:
        console.print(_render_table(columns=columns, rows=rows))
    else:
        console.print(_NONE_TEXT)


def _print_call_rows(console: Console, *, heading: str, rows: list[dict[str, object]]) -> None:
    _print_table_or_none(
        console,
        heading=heading,
        columns=[("kind", None), ("name", None), ("path", None), ("confidence", "right")],
        rows=rows,
    )


async def _infer_repo_root(graph) -> str | None:
    rows = await graph.query(
        "MATCH (n) WHERE n.kind = 'file' RETURN n.path AS path LIMIT 1000"
    )
    paths = [row.get("path") for row in rows if isinstance(row.get("path"), str) and row.get("path")]
    if not paths:
        return None

    normalized_paths = [os.path.normpath(path) for path in paths]
    common_path = os.path.commonpath(normalized_paths)
    if not common_path:
        return None

    candidate = Path(common_path)
    if candidate.is_file():
        candidate = candidate.parent
    return str(candidate)


@app.command()
def analyze(
    path: str = typer.Argument(..., help="Path to a repo or file"),
    docs: str | None = typer.Option(None, "--docs"),
    jira_project: str | None = typer.Option(None, "--jira-project"),
    jira_url: str | None = typer.Option(None, "--jira-url"),
    jira_email: str | None = typer.Option(None, "--jira-email"),
    jira_token: str | None = typer.Option(None, "--jira-token"),
    graph_name: str = typer.Option("loom", "--graph-name"),
    exclude_tests: bool = typer.Option(False, "--exclude-tests"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    from loom.core import LoomGraph
    from loom.ingest.integrations.jira import JiraConfig
    from loom.ingest.pipeline import index_repo

    console = Console()
    target = str(Path(path))
    console.print(f"Analyzing {target}...")

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)
        jira = None
        if jira_project and jira_url and jira_email and jira_token:
            jira = JiraConfig(
                base_url=jira_url,
                email=jira_email,
                api_token=jira_token,
                project_key=jira_project,
            )
        res = await index_repo(
            target,
            graph,
            force=force,
            exclude_tests=exclude_tests,
            docs_path=docs,
            jira=jira,
        )

        by_kind_rows = await graph.query(
            "MATCH (n) RETURN n.kind AS kind, count(n) AS c ORDER BY c DESC LIMIT 8"
        )

        console.print(
            _kv_table(
                [
                    ("file_count", str(res.file_count)),
                    ("files_skipped", str(res.files_skipped)),
                    ("files_updated", str(res.files_updated)),
                    ("files_added", str(res.files_added)),
                    ("files_deleted", str(res.files_deleted)),
                    ("nodes", str(res.node_count)),
                    ("edges", str(res.edge_count)),
                    ("errors", str(res.error_count)),
                    ("seconds", f"{res.duration_ms / 1000.0:.2f}"),
                ]
            )
        )

        if by_kind_rows:
            console.print(
                _render_table(
                    title="Top node kinds",
                    columns=[("kind", None), ("c", "right")],
                    rows=by_kind_rows,
                )
            )

        if res.error_count:
            console.print(
                _render_table(
                    title="Errors",
                    columns=[("phase", None), ("path", None), ("message", None)],
                    rows=[
                        {
                            "phase": err.phase,
                            "path": err.path,
                            "message": err.message,
                        }
                        for err in res.errors
                    ],
                )
            )

    asyncio.run(_run())


@app.command()
def trace(
    mode: str = typer.Argument(..., help="unimplemented|untraced|impact|tickets|coverage"),
    target: str | None = typer.Argument(None),
    graph_name: str = typer.Option("loom", "--graph-name"),
) -> None:
    from loom.core import LoomGraph
    from loom.query.traceability import (
        impact_of_ticket,
        sprint_code_coverage,
        tickets_for_function,
        unimplemented_tickets,
        untraced_functions,
    )

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if mode == "unimplemented":
            rows = await unimplemented_tickets(graph)
            _print_table_or_none(
                console,
                heading=None,
                columns=[("name", None), ("path", None)],
                rows=[{"name": n.name, "path": n.path} for n in rows],
            )
            return
        if mode == "untraced":
            rows = await untraced_functions(graph)
            _print_table_or_none(
                console,
                heading=None,
                columns=[("kind", None), ("name", None), ("path", None)],
                rows=[{"kind": n.kind.value, "name": n.name, "path": n.path} for n in rows],
            )
            return
        if mode == "impact":
            if not target:
                raise typer.Exit(code=1)
            rows = await impact_of_ticket(target, graph)
            _print_table_or_none(
                console,
                heading=None,
                columns=[("kind", None), ("name", None), ("path", None)],
                rows=[{"kind": n.kind.value, "name": n.name, "path": n.path} for n in rows],
            )
            return
        if mode == "tickets":
            if not target:
                raise typer.Exit(code=1)
            rows = await tickets_for_function(target, graph)
            _print_table_or_none(
                console,
                heading=None,
                columns=[("name", None), ("path", None)],
                rows=[{"name": n.name, "path": n.path} for n in rows],
            )
            return
        if mode == "coverage":
            if not target:
                raise typer.Exit(code=1)
            report = await sprint_code_coverage(target, graph)
            console.print(
                _kv_table(
                    [
                        ("sprint", report.sprint_name),
                        ("ticket_count", str(report.ticket_count)),
                        ("linked_function_count", str(report.linked_function_count)),
                    ]
                )
            )
            return

        raise typer.Exit(code=1)

    asyncio.run(_run())


@app.command()
def query(
    query_text: str = typer.Argument(..., help="Natural language query"),
    graph_name: str = typer.Option("loom", "--graph-name"),
    limit: int = typer.Option(10, "--limit"),
) -> None:
    from loom.core import LoomGraph
    from loom.search.searcher import search

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)
        results = await search(query_text, graph, limit=limit)
        _print_table_or_none(
            console,
            heading=None,
            columns=[("score", "right"), ("via", None), ("kind", None), ("name", None), ("path", None)],
            rows=[
                {
                    "score": f"{result.score:.3f}",
                    "via": result.matched_via,
                    "kind": result.node.kind.value,
                    "name": result.node.name,
                    "path": result.node.path,
                }
                for result in results
            ],
        )

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
    from loom.core import EdgeType, LoomGraph
    from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter
    from loom.core.node import NodeKind

    console = Console()
    calls_rel = EdgeTypeAdapter.to_storage(EdgeType.CALLS)

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
            f"MATCH (n{label_clause} {{name: $name}}) RETURN n.id AS id LIMIT 2",
            {"name": node},
        )
        if len(rows) != 1:
            return None
        return rows[0].get("id")

    async def _query_call_rows(graph: LoomGraph, query: str, params: dict[str, object]) -> list[dict[str, object]]:
        return await graph.query(query, params)

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if direction == "dump":
            rows = await _query_call_rows(
                graph,
                f"""
                    MATCH (a)-[r:{calls_rel}]->(b)
                    RETURN a.name AS from_name, a.path AS from_path,
                        b.name AS to_name, b.path AS to_path,
                        r.confidence AS confidence
                    LIMIT $limit
                    """,
                {"limit": limit},
            )
            formatted_rows = [
                {
                    "from": f"{row.get('from_name')} ({row.get('from_path')})",
                    "to": f"{row.get('to_name')} ({row.get('to_path')})",
                    "confidence": row.get("confidence"),
                }
                for row in rows
            ]
            _print_table_or_none(
                console,
                heading=None,
                columns=[("from", None), ("to", None), ("confidence", "right")],
                rows=formatted_rows,
            )
            return

        if not target:
            console.print("--target is required unless --direction dump")
            raise typer.Exit(code=1)

        node_id = await _resolve_node_id(graph, target)
        if node_id is None:
            console.print("Target not found")
            raise typer.Exit(code=1)

        if direction in {"callees", "both"}:
            rows = await _query_call_rows(
                graph,
                f"""
MATCH (a {{id: $id}})-[r:{calls_rel}]->(b)
RETURN b.kind AS kind, b.name AS name, b.path AS path, r.confidence AS confidence
ORDER BY confidence DESC
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            _print_call_rows(console, heading="=== callees ===", rows=rows)

        if direction in {"callers", "both"}:
            rows = await _query_call_rows(
                graph,
                f"""
MATCH (a)-[r:{calls_rel}]->(b {{id: $id}})
RETURN a.kind AS kind, a.name AS name, a.path AS path, r.confidence AS confidence
ORDER BY confidence DESC
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            _print_call_rows(console, heading="=== callers ===", rows=rows)

    asyncio.run(_run())


@app.command()
def entrypoints(
    graph_name: str = typer.Option("loom", "--graph-name"),
    limit: int = typer.Option(30, "--limit"),
) -> None:
    from loom.core import EdgeType, LoomGraph
    from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter

    console = Console()
    calls_rel = EdgeTypeAdapter.to_storage(EdgeType.CALLS)

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
            f"MATCH (n) "
            f"WHERE NOT ( ()-[:{calls_rel}]->(n) ) "
            f"WITH n "
            f"MATCH (n)-[:{calls_rel}]->(m) "
            f"RETURN n.kind AS kind, n.name AS name, n.path AS path, count(m) AS out_calls "
            f"ORDER BY out_calls DESC "
            f"LIMIT $limit"
        )
        r2 = await graph.query(q2, {"limit": limit})

        q3 = (
            "MATCH ()-[r]->() "
            "RETURN type(r) AS t, count(r) AS c "
            "ORDER BY c DESC "
            "LIMIT 20"
        )
        r3 = await graph.query(q3)

        _print_table_or_none(
            console,
            heading="=== name-based candidates ===",
            columns=[("kind", None), ("name", None), ("path", None)],
            rows=r1,
        )
        _print_table_or_none(
            console,
            heading="=== call roots (no incoming CALLS) ===",
            columns=[("out_calls", "right"), ("kind", None), ("name", None), ("path", None)],
            rows=r2,
        )
        relationship_rows = [{"type": row.get("t"), "count": row.get("c")} for row in r3]
        _print_table_or_none(
            console,
            heading="=== relationship types ===",
            columns=[("type", None), ("count", "right")],
            rows=relationship_rows,
        )

    asyncio.run(_run())


@app.command()
def enrich(
    graph_name: str = typer.Option("loom", "--graph-name"),
    repo_path: str | None = typer.Option(None, "--repo-path"),
    communities: bool = typer.Option(True, "--communities/--no-communities"),
    coupling: bool = typer.Option(True, "--coupling/--no-coupling"),
    coupling_months: int = typer.Option(6, "--coupling-months"),
    coupling_threshold: float = typer.Option(0.3, "--coupling-threshold"),
) -> None:
    """Run enrichment passes (communities, coupling) on an already-indexed graph.

    These are expensive operations best run once after initial indexing,
    not on every incremental update.

    Examples:
        uv run loom enrich --graph-name myrepo
        uv run loom enrich --graph-name myrepo --no-coupling
        uv run loom enrich --graph-name myrepo --coupling-months 3
    """
    from loom.core import LoomGraph

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if communities:
            from loom.analysis.code.communities import detect_communities

            console.print("Running community detection...")
            try:
                node_to_community = await detect_communities(graph)
                console.print(
                    f"Communities: {len(set(node_to_community.values()))} detected, "
                    f"{len(node_to_community)} nodes clustered"
                )
            except Exception as e:
                console.print(f"[red]Community detection failed: {e}[/red]")

        if coupling:
            from loom.analysis.code.coupling import analyze_coupling

            resolved_repo_path = repo_path or await _infer_repo_root(graph)
            if resolved_repo_path is None:
                console.print(
                    "[red]Coupling analysis failed: could not infer repo path from indexed file nodes; pass --repo-path explicitly[/red]"
                )
            else:
                console.print(
                    f"Analyzing git coupling for {resolved_repo_path} (last {coupling_months} months)..."
                )
                try:
                    edges = await analyze_coupling(
                        resolved_repo_path,
                        months=coupling_months,
                        threshold=coupling_threshold,
                    )
                    if edges:
                        await graph.bulk_create_edges(edges)
                    console.print(f"Coupling: {len(edges)} file pairs found")
                except Exception as e:
                    console.print(f"[red]Coupling analysis failed: {e}[/red]")

    asyncio.run(_run())


@app.command()
def serve(
    graph_name: str = typer.Option("loom", "--graph-name"),
) -> None:
    """Start the MCP server for Claude Code integration."""
    from loom.mcp.server import build_server

    console = Console()
    console.print("[bold green]Starting Loom MCP server...[/bold green]")
    console.print(f"Graph: {graph_name}")
    console.print(f"Database: {LOOM_DB_HOST}:{LOOM_DB_PORT}")

    mcp = build_server(graph_name=graph_name)
    mcp.run(transport="stdio")


@app.command()
def watch(
    path: str = typer.Argument(".", help="Path to watch"),
    graph_name: str = typer.Option("loom", "--graph-name"),
    debounce_ms: int = typer.Option(500, "--debounce"),
) -> None:
    """Watch a repository for changes and incrementally sync."""
    from loom.core import LoomGraph
    from loom.watch.watcher import watch_repo

    console = Console()
    console.print(f"[bold green]Watching {path} for changes...[/bold green]")
    console.print(f"Graph: {graph_name}")
    console.print(f"Debounce: {debounce_ms}ms")
    console.print("Press Ctrl+C to stop")

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)
        await watch_repo(path, graph, debounce_ms=debounce_ms)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching[/yellow]")


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

        console.print(
            _kv_table(
                [
                    ("files_updated", str(res.files_updated)),
                    ("files_added", str(res.files_added)),
                    ("files_deleted", str(res.files_deleted)),
                    ("nodes", str(res.node_count)),
                    ("edges", str(res.edge_count)),
                    ("errors", str(res.error_count)),
                    ("warnings", str(len(getattr(res, "warnings", [])))),
                    ("seconds", f"{res.duration_ms / 1000.0:.2f}"),
                ]
            )
        )

        warnings = getattr(res, "warnings", [])
        if warnings:
            console.print("Drift warnings:")
            for warning in warnings[:20]:
                console.print(f"  - {warning}")

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
