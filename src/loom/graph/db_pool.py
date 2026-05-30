from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path

from loom.graph.db import DB
from loom.graph.projects import ProjectRegistry

log = logging.getLogger(__name__)


class DBPool:
    """LRU cache of DB instances keyed by absolute DB path.

    Threadsafe via RLock. Evicted entries close their cached connection;
    in-flight callers hold their own reference and finish their query
    against the now-closed cache handle (SQLite WAL tolerates this — a
    new connection reopens on next get()).
    """

    def __init__(self, registry: ProjectRegistry, capacity: int = 8) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._registry = registry
        self._capacity = capacity
        self._lock = threading.RLock()
        self._cache: OrderedDict[Path, DB] = OrderedDict()
        self._default_path: Path | None = None

    @property
    def registry(self) -> ProjectRegistry:
        return self._registry

    def get(self, project: str | None, cwd: Path | None = None) -> DB:
        if project is None and self._default_path is not None:
            return self._get_by_path(self._default_path)
        name = project if project is not None else self._registry.current(cwd)
        path = self._registry.resolve(name)
        return self._get_by_path(path)

    def prime(self, db: DB) -> None:
        path = Path(db.path).resolve() if not isinstance(db.path, Path) else db.path.resolve()
        with self._lock:
            self._cache[path] = db
            self._cache.move_to_end(path)
            self._default_path = path
            self._evict_if_needed()

    def close_all(self) -> None:
        with self._lock:
            for db in self._cache.values():
                _safe_close(db)
            self._cache.clear()

    def _get_by_path(self, path: Path) -> DB:
        path = path.resolve()
        with self._lock:
            db = self._cache.get(path)
            if db is None:
                db = DB(path=path)
                db.connect()
                self._cache[path] = db
            self._cache.move_to_end(path)
            self._evict_if_needed()
            return db

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self._capacity:
            _, evicted = self._cache.popitem(last=False)
            _safe_close(evicted)


def _safe_close(db: DB) -> None:
    try:
        db.close()
    except Exception:
        log.warning("DBPool: failed to close DB at %s", db.path, exc_info=True)
