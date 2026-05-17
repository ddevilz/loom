from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import typer
from rich.console import Console

from loom.cli._app import app
from loom.cli.plugins import Plugin, get_plugins

console = Console()

_CLAUDE_SKILL_PATH = Path.home() / ".claude" / "skills" / "loom.md"
_CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
_SKILL_SRC = Path(__file__).parent.parent / "data" / "loom-skill.md"


# SessionStart hook: re-index changed files in background on every Claude Code session.
# Only fires if we're in a git repo and uvx is available. Non-blocking (&).
def _session_hook_cmd() -> str:
    """Build SessionStart hook command using absolute uvx path."""
    uvx = shutil.which("uvx") or "uvx"
    return (
        f"if [ -d .git ] && command -v {uvx} >/dev/null 2>&1; then"
        f" {uvx} --from loom-tool loom analyze . >/dev/null 2>&1 &"
        " fi"
    )


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


def _write_session_hook() -> bool:
    """Add a SessionStart hook to ~/.claude/settings.json that auto-runs loom analyze.

    Idempotent — skips write if the hook command is already present.

    Returns:
        True if hook was written or already present, False if write failed.
    """
    try:
        _CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if _CLAUDE_SETTINGS_PATH.exists():
            try:
                data = json.loads(_CLAUDE_SETTINGS_PATH.read_text())
            except json.JSONDecodeError:
                data = {}

        hooks = data.setdefault("hooks", {})
        session_hooks: list[dict] = hooks.setdefault("SessionStart", [])

        cmd = _session_hook_cmd()

        # Idempotency: don't add if hook command already present
        for entry in session_hooks:
            existing_hooks = entry.get("hooks", [])
            for h in existing_hooks:
                if h.get("command") == cmd:
                    return True

        session_hooks.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": cmd}],
            }
        )
        _CLAUDE_SETTINGS_PATH.write_text(json.dumps(data, indent=2) + "\n")
        return True
    except OSError:
        return False


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

    # Only write the Claude Code session hook when Claude Code was actually configured.
    claude_code_configured = any(p.name == "claude-code" for p in targets)
    if claude_code_configured and _write_session_hook():
        written.append(f"session hook: {_CLAUDE_SETTINGS_PATH} (auto-analyze on session start)")

    for line in written:
        console.print(f"[green]{line}[/green]")

    if not written:
        console.print("[yellow]nothing installed — no supported AI tools detected[/yellow]")
