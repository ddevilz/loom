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

# Skill written to ~/.claude/skills/loom.md so agents auto-load it
_CLAUDE_SKILL_PATH = Path.home() / ".claude" / "skills" / "loom.md"

_CLAUDE_SKILL = """\
---
name: loom
description: >
  Use Loom MCP tools for code intelligence — symbol search, context packets,
  blast radius, session primer, delta context. Invoke when working on any
  codebase that has been indexed with `loom analyze .`.
trigger: >
  When connected to an MCP server named "loom" OR when user says "use loom"
  OR when search_code / get_context / store_understanding tools are available.
---

# Loom Workflow

Loom is a persistent symbol index. Every session gets faster as agent summaries
accumulate. Zero LLM cost — all data from tree-sitter + your own stored summaries.

## Session start

Call `loom://primer` resource (or `loom context` CLI) for a ~200-token codebase
overview. Skip file exploration — primer gives you modules, hot functions, coverage.

If you have a `session_id` from last time:
```
get_delta(previous_session_id="<id>")  # only what changed
```
Otherwise:
```
start_session(agent_id="claude-code")  # store session_id for next time
```

## Finding code

```
search_code("validate token")   # FTS5 — returns summary + signature if cached
```
If result has `summary` → read it, skip file. Summary is authoritative.
If no summary → use `get_context(node_id)` before opening the file.

## Reasoning about a function

```
get_context("function:src/auth.py:validate_token")
```
Returns: summary, signature, callers (top 10), callees (top 10), staleness flag.
If `summary_stale: true` → source changed since summary written → re-read + update.

## Impact analysis

```
get_blast_radius("function:src/auth.py:validate_token", depth=3)
get_callers("function:src/auth.py:validate_token")
get_callees("function:src/auth.py:validate_token")
```

## Storing understanding (do this every time)

After reading any function:
```
store_understanding(
    node_id="function:src/auth.py:validate_token",
    summary="Validates JWT tokens, returns False if expired or signature invalid."
)
```
Good summary: what it does + why it exists. One sentence.
Bad: "handles auth" (vague), "calls jwt.decode()" (describes HOW not WHY).

Batch version for efficiency:
```
store_understanding_batch([
    {"node_id": "...", "summary": "..."},
    ...
])
```

## Node ID format

`{kind}:{path}:{symbol}`
Examples:
- `function:src/auth.py:validate_token`
- `class:src/models/user.py:User`
- `method:src/models/user.py:User.save`
- `file:src/auth.py`

## Key tools

| Tool | Use when |
|------|----------|
| `search_code(query)` | Finding symbols by name/keyword |
| `get_context(node_id)` | Full picture before reading source |
| `get_blast_radius(node_id)` | What breaks if this changes |
| `store_understanding(node_id, summary)` | After understanding any function |
| `get_delta(previous_session_id)` | Session start — what changed |
| `start_session(agent_id)` | Register session, get session_id |
| `graph_stats()` | Repo overview: counts by kind |
| `god_nodes()` | Most-called functions (good entry points) |
"""


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
    # Prefer uvx (works from PyPI without global install), fall back to loom binary
    servers["loom"] = {"command": "uvx", "args": ["loom-tool"]}
    cfg_path.write_text(json.dumps(data, indent=2) + "\n")


def _write_claude_skill() -> Path | None:
    """Write Loom workflow skill to ~/.claude/skills/loom.md."""
    try:
        _CLAUDE_SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CLAUDE_SKILL_PATH.write_text(_CLAUDE_SKILL)
        return _CLAUDE_SKILL_PATH
    except OSError:
        return None


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

    # Write Claude Code skill so agents auto-load Loom workflow instructions
    skill_path = _write_claude_skill()
    if skill_path:
        written.append(f"claude skill: {skill_path}")

    for line in written:
        console.print(f"[green]{line}[/green]")

    if not written:
        console.print("[yellow]nothing installed — no supported AI tools detected[/yellow]")
