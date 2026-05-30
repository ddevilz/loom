"""projects.py — list_projects MCP tool."""

from __future__ import annotations

from dataclasses import asdict


def register(mcp: object, pool: object, session: dict, cache: object) -> None:
    from loom.server.validation import ok

    @mcp.tool()  # type: ignore[attr-defined]
    async def list_projects() -> dict:
        """List all indexed Loom projects under ~/.loom/projects/.

        Returns name, path, db size, node count, and last-indexed timestamp
        for each *.db. Use the name in the `project=` arg on any read tool
        to scope queries to a specific project.
        """
        registry = pool._registry  # type: ignore[attr-defined]
        infos = []
        for p in registry.list():
            d = asdict(p)
            d["path"] = str(p.path)
            infos.append(d)
        return ok({"projects": infos, "current": registry.current()})
