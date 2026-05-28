"""cache.py — in-process memo cache for MCP tool results."""
from __future__ import annotations

import time

_MEMO_TTL = 300.0  # 5 min — matches Anthropic prompt-cache TTL


class MemoCache:
    """TTL-based in-memory cache for tool results keyed by tool+node_id."""

    __slots__ = ("_store", "_ttl")

    def __init__(self, ttl: float = _MEMO_TTL) -> None:
        self._store: dict[str, tuple[float, dict]] = {}
        self._ttl = ttl

    def make_key(self, tool: str, node_id: str, **extra: object) -> str:
        key = f"{tool}:{node_id}"
        if extra:
            key += ":" + ":".join(f"{k}={v}" for k, v in sorted(extra.items()))
        return key

    def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry and entry[0] > time.monotonic():
            return entry[1]
        self._store.pop(key, None)
        return None

    def set(self, key: str, result: dict) -> None:
        self._store[key] = (time.monotonic() + self._ttl, result)

    def invalidate(self, node_id: str) -> None:
        needle_mid = f":{node_id}:"
        needle_end = f":{node_id}"
        for k in [k for k in self._store if needle_mid in k or k.endswith(needle_end)]:
            del self._store[k]
