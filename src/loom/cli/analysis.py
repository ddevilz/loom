from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
<<<<<<< HEAD
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
=======
from loom.cli.formatters import _kv_table, _render_table


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
>>>>>>> main
