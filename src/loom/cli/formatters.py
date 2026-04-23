from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

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
