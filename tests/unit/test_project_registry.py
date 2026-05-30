from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from loom.graph.projects import ProjectRegistry, UnknownProjectError


def _make_db(path: Path, *, node_count: int = 0, last_ts: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, deleted_at INTEGER, updated_at INTEGER)"
    )
    for i in range(node_count):
        conn.execute(
            "INSERT INTO nodes (id, deleted_at, updated_at) VALUES (?, NULL, ?)",
            (f"n{i}", last_ts),
        )
    conn.commit()
    conn.close()


def test_resolve_known_project(tmp_path: Path) -> None:
    db = tmp_path / "loom.db"
    _make_db(db)
    reg = ProjectRegistry(projects_dir=tmp_path)
    assert reg.resolve("loom") == db


def test_resolve_unknown_raises(tmp_path: Path) -> None:
    reg = ProjectRegistry(projects_dir=tmp_path)
    with pytest.raises(UnknownProjectError):
        reg.resolve("nope")


def test_list_returns_metadata(tmp_path: Path) -> None:
    _make_db(tmp_path / "alpha.db", node_count=3, last_ts=1700000000)
    _make_db(tmp_path / "beta.db", node_count=0)
    reg = ProjectRegistry(projects_dir=tmp_path)
    infos = {p.name: p for p in reg.list()}
    assert set(infos) == {"alpha", "beta"}
    assert infos["alpha"].node_count == 3
    assert infos["alpha"].last_indexed == 1700000000
    assert infos["beta"].node_count == 0
    assert infos["alpha"].db_size_bytes > 0


def test_list_empty_dir(tmp_path: Path) -> None:
    reg = ProjectRegistry(projects_dir=tmp_path)
    assert reg.list() == []


def test_current_uses_cwd_dir_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    reg = ProjectRegistry(projects_dir=tmp_path / "_projects")
    # Non-git cwd: fall back to dir name
    assert reg.current() == tmp_path.name
