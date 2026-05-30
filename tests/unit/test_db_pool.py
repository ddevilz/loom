from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from loom.graph.db import DB
from loom.graph.db_pool import DBPool
from loom.graph.projects import ProjectRegistry, UnknownProjectError


def _make_indexed_db(path: Path) -> None:
    """Create a DB file at path with the loom schema initialised."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = DB(path=path)
    db.connect()
    db.close()


@pytest.fixture()
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectRegistry:
    pdir = tmp_path / "projects"
    pdir.mkdir()
    for name in ("a", "b", "c"):
        _make_indexed_db(pdir / f"{name}.db")
    monkeypatch.chdir(tmp_path)
    return ProjectRegistry(projects_dir=pdir)


def test_get_by_name(registry: ProjectRegistry) -> None:
    pool = DBPool(registry)
    db = pool.get("a")
    assert isinstance(db, DB)
    assert db.path == registry.resolve("a")


def test_get_returns_same_instance(registry: ProjectRegistry) -> None:
    pool = DBPool(registry)
    assert pool.get("a") is pool.get("a")


def test_unknown_project_raises(registry: ProjectRegistry) -> None:
    pool = DBPool(registry)
    with pytest.raises(UnknownProjectError):
        pool.get("missing")


def test_lru_eviction_closes_db(registry: ProjectRegistry, tmp_path: Path) -> None:
    pool = DBPool(registry, capacity=2)
    db_a = pool.get("a")
    pool.get("b")
    pool.get("c")
    assert db_a._conn is None
    db_a2 = pool.get("a")
    assert db_a2 is not db_a


def test_prime_registers_existing_db(registry: ProjectRegistry) -> None:
    pool = DBPool(registry, capacity=4)
    db = DB(path=registry.resolve("a"))
    db.connect()
    pool.prime(db)
    assert pool.get("a") is db


def test_threadsafe_smoke(registry: ProjectRegistry) -> None:
    pool = DBPool(registry, capacity=3)
    errors: list[BaseException] = []

    def worker(name: str) -> None:
        try:
            for _ in range(50):
                pool.get(name).connect()
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b", "c") * 3]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_get_none_resolves_current(registry: ProjectRegistry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_indexed_db(registry._dir / f"{tmp_path.name}.db")
    pool = DBPool(registry)
    db = pool.get(None)
    assert db.path.stem == tmp_path.name
