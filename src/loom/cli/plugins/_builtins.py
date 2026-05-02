"""Built-in platform plugins for loom install."""

from __future__ import annotations

from pathlib import Path

from loom.cli.plugins import Plugin, register

register(
    Plugin(
        name="claude-code",
        config_path=Path.home() / ".claude" / "mcp.json",
        config_key="mcpServers",
    )
)

register(
    Plugin(
        name="cursor",
        config_path=Path.home() / ".cursor" / "mcp.json",
        config_key="mcpServers",
    )
)

register(
    Plugin(
        name="windsurf",
        config_path=Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        config_key="mcpServers",
    )
)

register(
    Plugin(
        name="codex",
        config_path=Path.home() / ".codex" / "mcp.json",
        config_key="mcp",
    )
)
