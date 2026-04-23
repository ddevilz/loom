from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from loom.core.db import connect, has_fts5, init_schema

DEFAULT_DB_PATH: Path = Path.home() / ".loom" / "loom.db"


@dataclass
class DB:
    path: Path | str
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _fts5: bool | None = field(default=None, init=False, repr=False)

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._conn = connect(self.path)
                init_schema(self._conn)
                self._fts5 = has_fts5(self._conn)
            return self._conn
