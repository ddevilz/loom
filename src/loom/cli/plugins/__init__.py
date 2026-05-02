"""Loom install plugin system.

Each plugin declares one AI tool platform. Built-in plugins live in _builtins.py.
Custom plugins can be placed in ~/.loom/plugins/<name>.py — any file that calls
``register(plugin)`` at module level is picked up automatically.

Example custom plugin (~/.loom/plugins/my_editor.py):

    from loom.cli.plugins import Plugin, register
    from pathlib import Path

    register(Plugin(
        name="my-editor",
        config_path=Path.home() / ".my-editor" / "mcp.json",
        config_key="mcpServers",
    ))
"""
from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_USER_PLUGIN_DIR = Path.home() / ".loom" / "plugins"


@dataclass
class Plugin:
    """Describes one AI tool platform that Loom can configure.

    Args:
        name: Short identifier shown in CLI output (e.g. "cursor").
        config_path: Path to the platform's MCP JSON config file.
        config_key: Top-level JSON key that holds the servers dict
                    (e.g. "mcpServers" or "mcp" for Codex).
        server_entry: The JSON value written under ``config_key["loom"]``.
                      Defaults to ``{"command": "uvx", "args": ["loom-tool"]}``.
    """
    name: str
    config_path: Path
    config_key: str = "mcpServers"
    server_entry: dict = field(
        default_factory=lambda: {"command": "uvx", "args": ["loom-tool"]}
    )


_registry: list[Plugin] = []
_loaded = False


def register(plugin: Plugin) -> None:
    """Register a platform plugin. Safe to call multiple times with the same name."""
    if not any(p.name == plugin.name for p in _registry):
        _registry.append(plugin)


def get_plugins() -> list[Plugin]:
    """Return all registered plugins, loading builtins + user plugins on first call."""
    global _loaded
    if not _loaded:
        _loaded = True
        _load_builtins()
        _load_user_plugins()
    return list(_registry)


def _load_builtins() -> None:
    from loom.cli.plugins import _builtins  # noqa: F401 — side-effect: calls register()


def _load_user_plugins() -> None:
    if not _USER_PLUGIN_DIR.exists():
        return
    for path in sorted(_USER_PLUGIN_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"loom_plugin_{path.stem}", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Failed to load plugin %s: %s", path, exc)
