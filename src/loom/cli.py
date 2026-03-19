from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import typer
from rich.console import Console
from rich.table import Table

from loom import __version__
from loom.config import LOOM_DB_HOST, LOOM_DB_PORT
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.node_lookup import resolve_node_rows


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"loom {__version__}")
        raise typer.Exit()


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


def _print_call_rows(
    console: Console, *, heading: str, rows: list[dict[str, object]]
) -> None:
    _print_table_or_none(
        console,
        heading=heading,
        columns=[
            ("kind", None),
            ("name", None),
            ("path", None),
            ("confidence", "right"),
        ],
        rows=rows,
    )


def _print_context_rows(
    console: Console, *, heading: str, rows: list[dict[str, object]]
) -> None:
    _print_table_or_none(
        console,
        heading=heading,
        columns=[("kind", None), ("name", None), ("path", None), ("relation", None)],
        rows=rows,
    )


def _format_node_summary(name: str, path: str) -> str:
    return f"{name} ({Path(path).name})"


def _render_blast_branch(
    console: Console,
    *,
    node_id: str,
    children_by_parent: dict[str, list[dict[str, object]]],
    prefix: str = "",
) -> None:
    children = children_by_parent.get(node_id, [])
    for index, child in enumerate(children):
        is_last = index == len(children) - 1
        branch = "└─ " if is_last else "├─ "
        console.print(
            f"{prefix}{branch}{child['label']}    ← {child['edge_label']}{child['suffix']}"
        )
        next_prefix = prefix + ("   " if is_last else "│  ")
        _render_blast_branch(
            console,
            node_id=str(child["id"]),
            children_by_parent=children_by_parent,
            prefix=next_prefix,
        )


def _find_git_root(candidate: Path) -> Path | None:
    current = candidate
    if current.is_file():
        current = current.parent
    while True:
        if current.is_dir() and (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _infer_repo_root_from_paths(paths: list[str]) -> str | None:
    if not paths:
        return None
    use_posix = all("/" in path and "\\" not in path for path in paths)
    path_cls = PurePosixPath if use_posix else PureWindowsPath
    path_parts = [path_cls(path).parts for path in paths if path]
    if not path_parts:
        return None
    min_len = min(len(parts) for parts in path_parts)
    shared: list[str] = []
    for i in range(min_len):
        value = path_parts[0][i]
        if all(parts[i] == value for parts in path_parts[1:]):
            shared.append(value)
        else:
            break
    if not shared:
        return None
    candidate = path_cls(*shared)
    if candidate.name and "." in candidate.name:
        candidate = candidate.parent
    return str(candidate) if str(candidate) else None


async def _infer_repo_root(graph) -> str | None:
    rows = await graph.query(
        "MATCH (n) WHERE n.kind = 'file' RETURN n.path AS path LIMIT 1000"
    )
    paths = [
        row.get("path")
        for row in rows
        if isinstance(row.get("path"), str) and row.get("path")
    ]
    if not paths:
        return None

    if all("/" in path and "\\" not in path for path in paths):
        return _infer_repo_root_from_paths(paths)

    normalized_paths = [os.path.normpath(path) for path in paths]
    common_path = os.path.commonpath(normalized_paths)
    if not common_path:
        return None

    candidate = Path(common_path)
    git_root = _find_git_root(candidate)
    if git_root is not None:
        return str(git_root)
    return _infer_repo_root_from_paths(paths)


@app.command()
def analyze(
    path: str = typer.Argument(..., help="Path to a repo or file"),
    docs: str | None = typer.Option(None, "--docs"),
    jira_project: str | None = typer.Option(None, "--jira-project"),
    jira_jql: str | None = typer.Option(None, "--jira-jql"),
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
    target = str(Path(path).resolve())
    if not Path(target).exists():
        console.print(f"[red]Error:[/red] path does not exist: {target}")
        raise typer.Exit(code=1)
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
                jql=jira_jql,
            )
            console.print(f"Jira JQL: {jira.build_jql()}")
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

        if jira is not None:
            jira_rows = await graph.query(
                "MATCH (n) WHERE n.path STARTS WITH 'jira://' RETURN count(n) AS c"
            )
            jira_count = int((jira_rows or [{}])[0].get("c", 0) or 0)
            console.print(_kv_table([("jira_tickets", str(jira_count))]))

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

    try:
        asyncio.run(_run())
    except FileNotFoundError as exc:
        Console().print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def tickets(
    *,
    graph_name: str = typer.Option("loom", "--graph-name"),
    connected: bool = typer.Option(False, "--connected"),
    ticket: str | None = typer.Option(None, "--ticket"),
    limit: int = typer.Option(50, "--limit"),
) -> None:
    from loom.core import LoomGraph

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if not connected:
            console.print("Use --connected to show ticket connections.")
            return

        if ticket is None:
            rows = await graph.query(
                "MATCH (c:Node)-[:LOOM_IMPLEMENTS]->(t:Node) "
                "WHERE t.path STARTS WITH 'jira://' "
                "RETURN t.name AS ticket, t.path AS path, count(c) AS connected "
                "ORDER BY connected DESC, ticket ASC "
                "LIMIT $limit",
                {"limit": limit},
            )
            console.print(
                _render_table(
                    title="Connected Jira tickets",
                    columns=[("ticket", None), ("path", None), ("connected", "right")],
                    rows=rows,
                )
            )
            return

        ticket_path = f"jira://{ticket.split('-')[0]}/{ticket}"
        rows = await graph.query(
            "MATCH (c:Node)-[e:LOOM_IMPLEMENTS]->(t:Node) "
            "WHERE t.path = $ticket_path "
            "RETURN t.name AS ticket, c.kind AS kind, c.name AS name, c.path AS path, "
            "e.origin AS origin, e.confidence AS confidence "
            "ORDER BY confidence DESC "
            "LIMIT $limit",
            {"ticket_path": ticket_path, "limit": limit},
        )
        console.print(
            _render_table(
                title=f"Connections for {ticket}",
                columns=[
                    ("ticket", None),
                    ("kind", None),
                    ("name", None),
                    ("path", None),
                    ("origin", None),
                    ("confidence", "right"),
                ],
                rows=rows,
            )
        )

    asyncio.run(_run())


@app.command()
def trace(
    mode: str = typer.Argument(
        ..., help="unimplemented|untraced|impact|tickets|coverage"
    ),
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
                rows=[
                    {"kind": n.kind.value, "name": n.name, "path": n.path} for n in rows
                ],
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
                rows=[
                    {"kind": n.kind.value, "name": n.name, "path": n.path} for n in rows
                ],
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
            columns=[
                ("score", "right"),
                ("via", None),
                ("kind", None),
                ("name", None),
                ("path", None),
            ],
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
    target: str | None = typer.Option(
        None, "--target", help="Node id or plain name to inspect."
    ),
    graph_name: str = typer.Option("loom", "--graph-name"),
    kind: str | None = typer.Option(
        None, "--kind", help="Optional NodeKind when target is a plain name."
    ),
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
    from loom.query.node_lookup import (
        AmbiguousNodeError,
        NodeNotFoundError,
        resolve_node_id_from_rows,
    )

    console = Console()
    calls_rel = EdgeTypeAdapter.to_storage(EdgeType.CALLS)
    contains_rel = EdgeTypeAdapter.to_storage(EdgeType.CONTAINS)

    async def _resolve_node_id(graph: LoomGraph, node: str) -> str | None:
        resolved_kind: NodeKind | None = None
        if kind is not None:
            try:
                resolved_kind = NodeKind(kind)
            except Exception:  # noqa: BLE001
                console.print(f"Invalid --kind: {kind}")
                raise typer.Exit(code=1) from None

        rows = await resolve_node_rows(graph, target=node, kind=resolved_kind, limit=10)
        try:
            return resolve_node_id_from_rows(node, rows)
        except NodeNotFoundError:
            console.print(f"[red]Target not found:[/red] no node named [bold]{node!r}[/bold]")
            if kind is None:
                console.print(
                    "Tip: use [bold]--kind[/bold] (e.g. function, class, method) to narrow the search."
                )
            raise typer.Exit(code=1) from None
        except AmbiguousNodeError as exc:
            console.print(
                f"[yellow]Ambiguous target[/yellow]: {len(exc.rows)} nodes named [bold]{node!r}[/bold]. "
                "Pass the full node id or use [bold]--kind[/bold] to disambiguate:"
            )
            for r in exc.rows:
                console.print(f"  {r.get('id')}  ({r.get('kind')} · {r.get('path')})")
            raise typer.Exit(code=1) from None

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        if direction == "dump":
            rows = await graph.query(
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

        parent_rows = await graph.query(
            f"""
MATCH (a)-[:{contains_rel}]->(b {{id: $id}})
RETURN a.kind AS kind, a.name AS name, a.path AS path, 'parent' AS relation
LIMIT $limit
""",
            {"id": node_id, "limit": limit},
        )
        child_rows = await graph.query(
            f"""
MATCH (a {{id: $id}})-[:{contains_rel}]->(b)
RETURN b.kind AS kind, b.name AS name, b.path AS path, 'child' AS relation
LIMIT $limit
""",
            {"id": node_id, "limit": limit},
        )
        _print_context_rows(
            console, heading="=== lexical parents ===", rows=parent_rows
        )
        _print_context_rows(
            console, heading="=== lexical children ===", rows=child_rows
        )

        if direction in {"callees", "both"}:
            rows = await graph.query(
                f"""
MATCH (a {{id: $id}})-[r:{calls_rel}]->(b)
RETURN b.kind AS kind, b.name AS name, b.path AS path, r.confidence AS confidence
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            _print_call_rows(console, heading="=== callees ===", rows=rows)

        if direction in {"callers", "both"}:
            rows = await graph.query(
                f"""
MATCH (a)-[r:{calls_rel}]->(b {{id: $id}})
RETURN a.kind AS kind, a.name AS name, a.path AS path, r.confidence AS confidence
LIMIT $limit
""",
                {"id": node_id, "limit": limit},
            )
            _print_call_rows(console, heading="=== callers ===", rows=rows)

    asyncio.run(_run())


@app.command(name="blast_radius")
def blast_radius(
    node: str = typer.Option(..., "--node", help="Node id or plain name to inspect."),
    depth: int = typer.Option(3, "--depth", min=1, max=8),
    graph_name: str = typer.Option("loom", "--graph-name"),
    kind: str | None = typer.Option(
        None, "--kind", help="Optional NodeKind when node is a plain name."
    ),
) -> None:
    from loom.core import LoomGraph
    from loom.core.node import NodeKind
    from loom.query.node_lookup import (
        AmbiguousNodeError,
        NodeNotFoundError,
        resolve_node_id_from_rows,
    )

    console = Console()

    async def _resolve_node_id(graph: LoomGraph, target: str) -> str:
        resolved_kind: NodeKind | None = None
        if kind is not None:
            try:
                resolved_kind = NodeKind(kind)
            except Exception:  # noqa: BLE001
                console.print(f"Invalid --kind: {kind}")
                raise typer.Exit(code=1) from None

        rows = await resolve_node_rows(graph, target=target, kind=resolved_kind, limit=10)
        try:
            return resolve_node_id_from_rows(target, rows)
        except NodeNotFoundError:
            console.print(f"[red]Target not found:[/red] no node named [bold]{target!r}[/bold]")
            if kind is None:
                console.print(
                    "Tip: use [bold]--kind[/bold] (e.g. function, class, method) to narrow the search."
                )
            raise typer.Exit(code=1) from None
        except AmbiguousNodeError as exc:
            console.print(
                f"[yellow]Ambiguous target[/yellow]: {len(exc.rows)} nodes named [bold]{target!r}[/bold]. "
                "Pass the full node id or use [bold]--kind[/bold] to disambiguate:"
            )
            for row in exc.rows:
                console.print(f"  {row.get('id')}  ({row.get('kind')} · {row.get('path')})")
            raise typer.Exit(code=1) from None

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)
        node_id = await _resolve_node_id(graph, node)
        payload = await build_blast_radius_payload(graph, node_id=node_id, depth=depth)
        root = payload.get("root")
        if not isinstance(root, dict):
            console.print(f"[red]Node not found:[/red] {node_id}")
            raise typer.Exit(code=1)

        summary = payload.get("summary", {})
        total_nodes = int(summary.get("total_nodes", 0))
        hops = int(summary.get("hops", 0))
        console.print(f"Blast radius: {total_nodes} nodes across {hops} hops")
        console.print()
        console.print(_format_node_summary(str(root["name"]), str(root["path"])))

        children_by_parent: dict[str, list[dict[str, object]]] = {}
        callers = payload.get("callers", [])
        for blast_node in sorted(
            [row for row in callers if isinstance(row, dict)],
            key=lambda item: (
                int(item.get("depth", 0)),
                str(item.get("path", "")).lower(),
                str(item.get("name", "")).lower(),
            ),
        ):
            parent_id = str(blast_node.get("parent_id") or node_id)
            children_by_parent.setdefault(parent_id, []).append(
                {
                    "id": str(blast_node.get("id") or ""),
                    "label": _format_node_summary(
                        str(blast_node.get("name") or ""),
                        str(blast_node.get("path") or ""),
                    ),
                    "edge_label": str(blast_node.get("edge_label") or "CALLS"),
                    "suffix": "",
                }
            )

        docs_at_risk = payload.get("docs_at_risk", [])
        for row in [row for row in docs_at_risk if isinstance(row, dict)]:
            children_by_parent.setdefault(node_id, []).append(
                {
                    "id": str(row.get("id") or ""),
                    "label": Path(str(row.get("path") or "")).name,
                    "edge_label": str(row.get("edge_label") or "IMPLEMENTS"),
                    "suffix": str(row.get("suffix") or ""),
                }
            )

        _render_blast_branch(
            console, node_id=node_id, children_by_parent=children_by_parent
        )

        warnings = payload.get("warnings", [])
        if warnings:
            console.print()
            for warning in warnings:
                console.print(f"⚠  {warning}")

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
            columns=[
                ("out_calls", "right"),
                ("kind", None),
                ("name", None),
                ("path", None),
            ],
            rows=r2,
        )
        relationship_rows = [
            {"type": row.get("t"), "count": row.get("c")} for row in r3
        ]
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
def relink(
    graph_name: str = typer.Option("loom", "--graph-name"),
    embedding_threshold: float = typer.Option(0.75, "--embedding-threshold"),
    name_threshold: float = typer.Option(0.6, "--name-threshold"),
) -> None:
    """Re-run the semantic linker on all graph nodes without re-indexing.

    Fetches all code nodes and doc nodes already in the graph and re-creates
    LOOM_IMPLEMENTS edges. Use this after importing new Jira tickets or after
    adjusting similarity thresholds — no file parsing or re-embedding needed
    if embeddings are already stored.

    Examples:
        loom relink --graph-name loom_repo
        loom relink --graph-name loom_repo --embedding-threshold 0.8
    """
    from loom.core import LoomGraph
    from loom.ingest.utils import get_code_nodes_for_linking, get_doc_nodes_for_linking
    from loom.linker.linker import SemanticLinker

    console = Console()

    async def _run() -> None:
        graph = LoomGraph(graph_name=graph_name)

        console.print("Fetching code nodes from graph...")
        code_nodes = await get_code_nodes_for_linking(graph)
        console.print(f"  {len(code_nodes)} code nodes loaded")

        console.print("Fetching doc nodes from graph...")
        doc_nodes = await get_doc_nodes_for_linking(graph)
        console.print(f"  {len(doc_nodes)} doc nodes loaded")

        if not code_nodes:
            console.print("[yellow]No code nodes found — index a repo first.[/yellow]")
            return
        if not doc_nodes:
            console.print(
                "[yellow]No doc nodes found — index docs or Jira tickets first.[/yellow]"
            )
            return

        console.print(
            f"Linking {len(code_nodes)} code nodes with {len(doc_nodes)} doc nodes..."
        )
        from time import perf_counter

        t0 = perf_counter()
        linker = SemanticLinker(
            embedding_threshold=embedding_threshold,
            name_threshold=name_threshold,
        )
        edges = await linker.link(code_nodes, doc_nodes, graph)
        elapsed = perf_counter() - t0
        console.print(f"Created {len(edges)} LOOM_IMPLEMENTS edges in {elapsed:.2f}s")

    asyncio.run(_run())


@app.command()
def serve(
    graph_name: str = typer.Option("loom", "--graph-name"),
) -> None:
    """Start the MCP server for Claude Code integration."""
    from loom.mcp.server import build_server

    # All startup output MUST go to stderr — stdout is reserved for the MCP
    # stdio JSON-RPC transport. Any text on stdout will corrupt the protocol.
    Console(stderr=True).print(
        f"[bold green]Starting Loom MCP server...[/bold green] graph={graph_name} db={LOOM_DB_HOST}:{LOOM_DB_PORT}"
    )

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
            raise typer.Exit(code=1) from e

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
                    ("warnings", str(len(res.warnings))),
                    ("seconds", f"{res.duration_ms / 1000.0:.2f}"),
                ]
            )
        )

        warnings = res.warnings
        if warnings:
            console.print("Drift warnings:")
            for warning in warnings[:20]:
                console.print(f"  - {warning}")

        if res.error_count:
            console.print("Review errors in output.")

    asyncio.run(_run())


@app.command()
def setup() -> None:
    """Configure your shell so 'loom' is available on PATH after install.

    Run this once after installing loom to permanently add it to your PATH.
    Supports zsh, bash, and fish on macOS/Linux, and prints manual instructions
    for Windows or any other shell.

    Examples:
        loom setup          # interactive — detects your shell and offers to patch RC
        loom setup          # safe: never overwrites existing PATH entries
    """
    import shutil
    import sysconfig

    console = Console()

    bin_dir = Path(sysconfig.get_path("scripts"))
    loom_bin = bin_dir / "loom"

    already_on_path = shutil.which("loom") is not None

    console.print("\n[bold]Loom setup[/bold]")
    console.print(f"Installed binary : {loom_bin}")
    console.print(f"Scripts directory: {bin_dir}")

    if already_on_path:
        found = shutil.which("loom")
        console.print(f"\n[green]✓ loom is already on your PATH[/green] ({found})")
        return

    console.print(f"\n[yellow]⚠  {bin_dir} is not on your PATH.[/yellow]")
    console.print(
        "Add it now so you can run [bold]loom[/bold] directly from any terminal.\n"
    )

    shell = os.environ.get("SHELL", "")
    home = Path.home()

    if sys.platform == "win32":
        console.print("[bold]Windows — add to PATH manually:[/bold]")
        console.print("  1. Open Start → search 'environment variables'")
        console.print("  2. Edit the [bold]Path[/bold] variable and append:")
        console.print(f"     [cyan]{bin_dir}[/cyan]")
        console.print("  3. Restart your terminal.")
        return

    if "zsh" in shell:
        rc_file = home / ".zshrc"
        shell_name = "zsh"
    elif "fish" in shell:
        rc_file = home / ".config" / "fish" / "config.fish"
        shell_name = "fish"
    else:
        rc_file = home / ".bashrc"
        shell_name = "bash"

    export_line = (
        f'fish_add_path "{bin_dir}"'
        if shell_name == "fish"
        else f'export PATH="{bin_dir}:$PATH"'
    )

    console.print(
        f"Detected shell: [bold]{shell_name}[/bold]  →  RC file: [bold]{rc_file}[/bold]"
    )
    console.print(f"\nLine to add:\n  [cyan]{export_line}[/cyan]\n")

    answer = (
        typer.prompt(
            f"Append this line to {rc_file} automatically? [y/N]",
            default="N",
        )
        .strip()
        .lower()
    )

    if answer != "y":
        console.print(
            "\nNo changes made. Add the line manually then restart your terminal."
        )
        return

    rc_file.parent.mkdir(parents=True, exist_ok=True)
    existing = rc_file.read_text(encoding="utf-8") if rc_file.exists() else ""

    if str(bin_dir) in existing:
        console.print(
            f"\n[green]✓ {bin_dir} is already referenced in {rc_file}[/green]"
        )
        return

    with rc_file.open("a", encoding="utf-8") as f:
        f.write(f"\n# Added by loom setup\n{export_line}\n")

    console.print(f"\n[green]✓ Written to {rc_file}[/green]")
    console.print(f"Restart your terminal or run:  [bold]source {rc_file}[/bold]")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Development mode (placeholder)."),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
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
