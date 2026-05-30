from __future__ import annotations

import contextlib
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PROJECTS_DIR: Path = Path.home() / ".loom" / "projects"


class UnknownProjectError(KeyError):
    """Raised when a project name does not map to an indexed DB."""


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    path: Path
    db_size_bytes: int
    node_count: int
    last_indexed: int | None


class ProjectRegistry:
    """Stateless reader over ~/.loom/projects/*.db.

    Resolves short project names to DB paths and surfaces lightweight
    metadata (node count, last indexed) for the MCP `list_projects` tool.
    """

    def __init__(self, projects_dir: Path = _DEFAULT_PROJECTS_DIR) -> None:
        self._dir = projects_dir

    def resolve(self, name: str) -> Path:
        path = self._dir / f"{name}.db"
        if not path.exists():
            raise UnknownProjectError(name)
        return path

    def list(self) -> list[ProjectInfo]:
        if not self._dir.exists():
            return []
        out: list[ProjectInfo] = []
        for db_path in sorted(self._dir.glob("*.db")):
            out.append(self._inspect(db_path))
        return out

    def current(self, cwd: Path | None = None) -> str:
        base = (cwd or Path.cwd()).resolve()
        with contextlib.suppress(Exception):
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=base,
                timeout=3,
            )
            if result.returncode == 0:
                return Path(result.stdout.strip()).name
        return base.name

    @staticmethod
    def _inspect(db_path: Path) -> ProjectInfo:
        size = db_path.stat().st_size
        node_count = 0
        last_indexed: int | None = None
        with contextlib.suppress(sqlite3.Error):
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS c, MAX(updated_at) AS ts "
                    "FROM nodes WHERE deleted_at IS NULL"
                ).fetchone()
                if row is not None:
                    node_count = int(row[0] or 0)
                    last_indexed = int(row[1]) if row[1] is not None else None
            finally:
                conn.close()
        return ProjectInfo(
            name=db_path.stem,
            path=db_path,
            db_size_bytes=size,
            node_count=node_count,
            last_indexed=last_indexed,
        )
