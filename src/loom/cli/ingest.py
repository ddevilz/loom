from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.cli.formatters import _kv_table
from loom.config import LOOM_DB_HOST, LOOM_DB_PORT


def _infer_repo_root_from_paths(paths: list[str]) -> str | None:
    from pathlib import PurePosixPath, PureWindowsPath

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


async def _infer_repo_root(graph) -> str | None:
    rows = await graph.query(
        "MATCH (n:File) RETURN n.path AS path LIMIT 1000"
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
    embedding_threshold: float = typer.Option(0.85, "--embedding-threshold"),
) -> None:
    """Re-run the semantic linker on all graph nodes without re-indexing.

    Fetches all code nodes and markdown doc nodes already in the graph and
    re-creates LOOM_IMPLEMENTS edges based on embedding similarity. Use this
    after adjusting similarity thresholds — no file parsing or re-embedding
    needed if embeddings are already stored.

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
        all_doc_nodes = await get_doc_nodes_for_linking(graph)
        # Only link markdown doc nodes — Jira ticket linking is handled by git_linker
        doc_nodes = [n for n in all_doc_nodes if not (n.path or "").startswith("jira://")]
        console.print(f"  {len(doc_nodes)} markdown doc nodes loaded")

        if not code_nodes:
            console.print("[yellow]No code nodes found — index a repo first.[/yellow]")
            return
        if not doc_nodes:
            console.print(
                "[yellow]No markdown doc nodes found — index docs first.[/yellow]"
            )
            return

        console.print(
            f"Linking {len(code_nodes)} code nodes with {len(doc_nodes)} doc nodes..."
        )
        from time import perf_counter

        t0 = perf_counter()
        linker = SemanticLinker(
            embedding_threshold=embedding_threshold,
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
