from __future__ import annotations

import json
import stat
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app

console = Console()

_PLATFORMS: dict[str, Path] = {
    "claude-code": Path.home() / ".claude" / "mcp.json",
    "cursor": Path.home() / ".cursor" / "mcp.json",
    "windsurf": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    "codex": Path.home() / ".codex" / "mcp.json",
}


def _write_mcp_config(platform: str, cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text())
        except json.JSONDecodeError:
            data = {}
    key = "mcp" if platform == "codex" else "mcpServers"
    servers = data.setdefault(key, {})
    servers["loom"] = {"command": "loom", "args": ["serve"]}
    cfg_path.write_text(json.dumps(data, indent=2) + "\n")


def _install_git_hook(repo: Path) -> Path:
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        'loom sync \\\n'
        '  --old-sha "$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD)" \\\n'
        '  --new-sha "$(git rev-parse HEAD)"\n'
    )
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return hook


@app.command()
def install(
    platform: str | None = typer.Option(None, "--platform", help="Specific platform to configure"),
    repo: Path = typer.Option(Path(), "--repo", help="Repo root for post-commit hook"),
) -> None:
    """Auto-configure MCP for AI tools and install git post-commit hook."""
    platforms = [platform] if platform else list(_PLATFORMS.keys())
    written: list[str] = []

    for p in platforms:
        target = _PLATFORMS.get(p)
        if target is None:
            console.print(f"[yellow]unknown platform: {p}[/yellow]")
            continue
        # Skip auto-detected platforms whose config dirs don't exist
        if platform is None and not target.parent.exists():
            continue
        _write_mcp_config(p, target)
        written.append(f"{p}: {target}")

    repo_resolved = repo.resolve()
    if (repo_resolved / ".git").exists():
        hook_path = _install_git_hook(repo_resolved)
        written.append(f"post-commit hook: {hook_path}")

    for line in written:
        console.print(f"[green]{line}[/green]")

    if not written:
        console.print("[yellow]nothing installed — no supported AI tools detected[/yellow]")
