from __future__ import annotations

import typer

from loom import __version__
from loom.cli._app import app


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"loom {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        raise typer.Exit(code=0)


def main() -> int:
    try:
        app(prog_name="loom")
        return 0
    except SystemExit as e:
        code = e.code
        return int(code) if isinstance(code, int) else 0


# Register sub-commands by importing their modules (side-effect: app.command() decorators run)
import loom.cli.analysis as _analysis  # noqa: E402, F401
import loom.cli.export as _export  # noqa: E402, F401
import loom.cli.graph as _graph  # noqa: E402, F401
import loom.cli.ingest as _ingest  # noqa: E402, F401
import loom.cli.install as _install  # noqa: E402, F401
from loom.cli.analysis import communities, dead_code  # noqa: E402, F401
from loom.cli.export import export_graph  # noqa: E402, F401
from loom.cli.graph import (  # noqa: E402, F401
    blast_radius,
    callees,
    callers,
    query,
    stats,
    summaries,
)
from loom.cli.ingest import analyze, serve, sync  # noqa: E402, F401
from loom.cli.install import install  # noqa: E402, F401

__all__ = [
    "app",
    "main",
    "analyze",
    "sync",
    "serve",
    "blast_radius",
    "callers",
    "callees",
    "query",
    "stats",
    "communities",
    "dead_code",
    "install",
    "export_graph",
    "summaries",
]
