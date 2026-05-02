from __future__ import annotations

import json
import stat
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.cli.plugins import Plugin, get_plugins

console = Console()

_CLAUDE_SKILL_PATH = Path.home() / ".claude" / "skills" / "loom.md"
_SKILL_SRC = Path(__file__).parent.parent / "data" / "loom-skill.md"


def _write_mcp_config(plugin: Plugin) -> None:
    plugin.config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if plugin.config_path.exists():
        try:
            data = json.loads(plugin.config_path.read_text())
        except json.JSONDecodeError:
            data = {}
    data.setdefault(plugin.config_key, {})["loom"] = plugin.server_entry
    plugin.config_path.write_text(json.dumps(data, indent=2) + "\n")


def _write_claude_skill() -> Path | None:
    try:
        _CLAUDE_SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CLAUDE_SKILL_PATH.write_text(_SKILL_SRC.read_text())
        return _CLAUDE_SKILL_PATH
    except OSError:
        return None


def _install_git_hook(repo: Path) -> Path:
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "#!/bin/sh\n"
        "loom sync \\\n"
        '  --old-sha "$(git rev-parse HEAD~1 2>/dev/null || git rev-parse HEAD)" \\\n'
        '  --new-sha "$(git rev-parse HEAD)"\n'
    )
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    return hook


@app.command()
def install(
    platform: str | None = typer.Option(None, "--platform", help="Specific platform to configure"),
    repo: Path = typer.Option(Path(), "--repo", help="Repo root for post-commit hook"),
    list_plugins: bool = typer.Option(False, "--list-plugins", help="List platform plugins"),
) -> None:
    """Auto-configure MCP for AI tools and install git post-commit hook."""
    plugins = get_plugins()

    if list_plugins:
        for p in plugins:
            console.print(f"  [cyan]{p.name}[/cyan]  →  {p.config_path}")
        return

    if platform:
        targets = [p for p in plugins if p.name == platform]
        if not targets:
            console.print(f"[red]unknown platform: {platform}[/red]")
            console.print(f"available: {', '.join(p.name for p in plugins)}")
            raise typer.Exit(1)
    else:
        # Auto-detect: only configure platforms whose config dir exists
        targets = [p for p in plugins if p.config_path.parent.exists()]

    written: list[str] = []
    for plugin in targets:
        _write_mcp_config(plugin)
        written.append(f"{plugin.name}: {plugin.config_path}")

    repo_resolved = repo.resolve()
    if (repo_resolved / ".git").exists():
        hook_path = _install_git_hook(repo_resolved)
        written.append(f"post-commit hook: {hook_path}")

    skill_path = _write_claude_skill()
    if skill_path:
        written.append(f"claude skill: {skill_path}")

    for line in written:
        console.print(f"[green]{line}[/green]")

    if not written:
        console.print("[yellow]nothing installed — no supported AI tools detected[/yellow]")
