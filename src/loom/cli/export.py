from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.graph.db import DB, DEFAULT_DB_PATH
from loom.store.nodes import get_export_rows

console = Console()

_TEMPLATE = Path(__file__).parent.parent / "templates" / "graph.html"

# ── colour palette per node kind ─────────────────────────────────────────────
_KIND_COLOURS: dict[str, str] = {
    "function": "#4f8ef7",
    "method": "#7c5cbf",
    "class": "#f0a500",
    "module": "#3aafa9",
    "interface": "#e07b54",
    "enum": "#c75d9d",
    "type": "#9ab87a",
    "file": "#8da9b4",
    "community": "#d4d4d4",
}
_DEFAULT_COLOUR = "#aaaaaa"

# ── edge colours ──────────────────────────────────────────────────────────────
_EDGE_COLOURS: dict[str, str] = {
    "calls": "#e74c3c",
    "imports": "#3498db",
    "extends": "#2ecc71",
    "child_of": "#f39c12",
    "contains": "#95a5a6",
    "coupled_with": "#9b59b6",
    "member_of": "#1abc9c",
}
_DEFAULT_EDGE_COLOUR = "#888888"


def _build_graph_data(db: DB) -> dict:
    node_rows, edge_rows = get_export_rows(db)

    nodes = []
    for r in node_rows:
        colour = _KIND_COLOURS.get(r["kind"], _DEFAULT_COLOUR)
        label = r["name"]
        nodes.append(
            {
                "data": {
                    "id": r["id"],
                    "label": label,
                    "kind": r["kind"],
                    "path": r["path"],
                    "language": r["language"] or "",
                    "is_dead_code": bool(r["is_dead_code"]),
                    "colour": colour,
                }
            }
        )

    edges = []
    seen: set[tuple[str, str, str]] = set()
    for r in edge_rows:
        key = (r["from_id"], r["to_id"], r["kind"])
        if key in seen:
            continue
        seen.add(key)
        colour = _EDGE_COLOURS.get(r["kind"], _DEFAULT_EDGE_COLOUR)
        edges.append(
            {
                "data": {
                    "id": f"{r['from_id']}__{r['to_id']}__{r['kind']}",
                    "source": r["from_id"],
                    "target": r["to_id"],
                    "kind": r["kind"],
                    "colour": colour,
                }
            }
        )

    kinds = sorted({r["kind"] for r in node_rows})
    edge_kinds = sorted({r["kind"] for r in edge_rows})
    return {"nodes": nodes, "edges": edges, "kinds": kinds, "edge_kinds": edge_kinds}


def _render_html(data: dict, db_path: Path) -> str:
    graph_json = json.dumps(data, separators=(",", ":"))
    return (
        _TEMPLATE.read_text(encoding="utf-8")
        .replace("__GRAPH_JSON__", graph_json)
        .replace("__DB_NAME__", db_path.name)
    )


@app.command(name="export")
def export_graph(
    output: Path = typer.Argument(Path("loom-graph.html"), help="Output HTML file path"),
    db: Path | None = typer.Option(None, "--db", help="Path to loom.db"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open in browser"),
) -> None:
    """Export the code graph as a self-contained interactive HTML file."""
    db_obj = DB(path=db or DEFAULT_DB_PATH)
    data = _build_graph_data(db_obj)
    html = _render_html(data, Path(str(db_obj.path)))
    output.write_text(html, encoding="utf-8")
    console.print(
        f"[green]✓[/green] Exported {len(data['nodes'])} nodes, "
        f"{len(data['edges'])} edges → [bold]{output}[/bold]"
    )
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
