"""FingerprintRepository — file-level change detection storage."""
from __future__ import annotations

import time
from dataclasses import dataclass
from loom.graph.db import DB


@dataclass
class FileFingerprint:
    file_path: str
    content_sha: str
    mtime_ns: int
    indexed_at: float


class FingerprintRepository:
    def __init__(self, db: DB) -> None:
        self._db = db

    def get_all(self) -> dict[str, FileFingerprint]:
        """Return all stored fingerprints as path → FileFingerprint."""
        with self._db._lock:
            conn = self._db.connect()
            rows = conn.execute(
                "SELECT file_path, content_sha, mtime_ns, indexed_at FROM file_fingerprints"
            ).fetchall()
            return {
                r["file_path"]: FileFingerprint(
                    file_path=r["file_path"],
                    content_sha=r["content_sha"],
                    mtime_ns=r["mtime_ns"],
                    indexed_at=r["indexed_at"],
                )
                for r in rows
            }

    def upsert(self, fingerprints: list[FileFingerprint]) -> int:
        """Insert or update fingerprints. Returns count written."""
        if not fingerprints:
            return 0
        with self._db._lock:
            conn = self._db.connect()
            conn.executemany(
                """INSERT INTO file_fingerprints (file_path, content_sha, mtime_ns, indexed_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(file_path) DO UPDATE SET
                       content_sha = excluded.content_sha,
                       mtime_ns    = excluded.mtime_ns,
                       indexed_at  = excluded.indexed_at""",
                [(fp.file_path, fp.content_sha, fp.mtime_ns, fp.indexed_at) for fp in fingerprints],
            )
            conn.commit()
            return len(fingerprints)

    def delete_paths(self, paths: list[str]) -> int:
        """Delete fingerprints for given paths. Returns count deleted."""
        if not paths:
            return 0
        with self._db._lock:
            conn = self._db.connect()
            placeholders = ",".join("?" * len(paths))
            cursor = conn.execute(
                f"DELETE FROM file_fingerprints WHERE file_path IN ({placeholders})", paths
            )
            conn.commit()
            return cursor.rowcount

    def update_mtime(self, file_path: str, mtime_ns: int) -> None:
        """Update only the mtime for a file (touch with no content change)."""
        with self._db._lock:
            conn = self._db.connect()
            conn.execute(
                "UPDATE file_fingerprints SET mtime_ns = ? WHERE file_path = ?",
                (mtime_ns, file_path),
            )
            conn.commit()
