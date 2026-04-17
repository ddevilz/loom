from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from loom.cli._app import app
from loom.cli.formatters import (
    _format_node_summary,
    _print_call_rows,
    _print_context_rows,
    _print_table_or_none,
    _render_blast_branch,
)
from loom.query.blast_radius import build_blast_radius_payload
from loom.query.node_lookup import resolve_node_rows


@app.command()
def trace(
    mode: str = typer.Argument(
        ..., help="unimplemented|untraced|impact|tickets|coverage"
    ),
    target: str | None = typer.Argument(None),
    graph_name: str = typer.Option("loom", "--graph-name"),
) -> None:
    from loom.cli.formatters import _kv_table
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
            console.print(
                f"[red]Target not found:[/red] no node named [bold]{node!r}[/bold]"
            )
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
    from pathlib import Path

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

        rows = await resolve_node_rows(
            graph, target=target, kind=resolved_kind, limit=10
        )
        try:
            return resolve_node_id_from_rows(target, rows)
        except NodeNotFoundError:
            console.print(
                f"[red]Target not found:[/red] no node named [bold]{target!r}[/bold]"
            )
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
                console.print(
                    f"  {row.get('id')}  ({row.get('kind')} · {row.get('path')})"
                )
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
