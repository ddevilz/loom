from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

import typer

from loom import __version__
from loom.cli._app import app


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"loom {__version__}")
        raise typer.Exit()


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
        from rich.console import Console

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


# Register commands from domain modules as a side effect of importing them.
# These imports MUST come after `app` and `_root` are defined.
import loom.cli.analysis as _analysis  # noqa: E402, F401
import loom.cli.graph as _graph  # noqa: E402, F401
import loom.cli.ingest as _ingest  # noqa: E402, F401
from loom.cli.analysis import analyze, tickets  # noqa: E402, F401

# Re-export command functions so that `from loom.cli import <cmd>` still works.
from loom.cli.graph import (  # noqa: E402, F401
    blast_radius,
    calls,
    entrypoints,
    query,
    trace,
)
from loom.cli.ingest import (  # noqa: E402, F401
    enrich,
    relink,
    serve,
    setup,
    sync,
    watch,
)

__all__ = [
    "app",
    "main",
    "trace",
    "query",
    "calls",
    "blast_radius",
    "entrypoints",
    "enrich",
    "relink",
    "serve",
    "watch",
    "sync",
    "setup",
    "analyze",
    "tickets",
]
