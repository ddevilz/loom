from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loom.ingest.pipeline import index_repo


@dataclass
class FakeGraph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    bulk_nodes_calls: int = 0

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if cypher.strip() == "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash":
            return [
                {"id": node_id, "content_hash": props.get("content_hash")}
                for node_id, props in self.nodes.items()
                if props.get("kind") == "file"
            ]

        if cypher.strip() == "MATCH (n) RETURN count(n) AS c":
            return [{"c": len(self.nodes)}]

        if cypher.strip() == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": 0}]

        if cypher.strip().startswith("MATCH (a {path: $path})-[r]->()"):
            # Edge invalidation queries are accepted but ignored by this fake.
            return []

        if cypher.strip() == "MATCH (n {id: $id}) DETACH DELETE n":
            assert params is not None
            node_id = params["id"]
            self.nodes.pop(node_id, None)
            return []

        raise AssertionError(f"Unexpected cypher: {cypher}")

    async def bulk_create_nodes(self, nodes: list[Any]) -> None:
        self.bulk_nodes_calls += 1
        for n in nodes:
            self.nodes[n.id] = n.model_dump()

    async def bulk_create_edges(self, edges: list[Any]) -> None:
        return None


def _write(tmp_path: Path, rel: str, text: str) -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


@pytest.mark.asyncio
async def test_index_repo_skips_unchanged_files(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "def g():\n    return 2\n")

    g = FakeGraph()

    r1 = await index_repo(str(tmp_path), g, force=False)
    assert r1.files_added == 2
    assert r1.files_updated == 0
    assert r1.files_skipped == 0

    r2 = await index_repo(str(tmp_path), g, force=False)
    assert r2.files_added == 0
    assert r2.files_updated == 0
    assert r2.files_skipped == 2


@pytest.mark.asyncio
async def test_index_repo_updates_only_changed_file(tmp_path: Path) -> None:
    a = _write(tmp_path, "a.py", "def f():\n    return 1\n")
    _write(tmp_path, "b.py", "def g():\n    return 2\n")

    g = FakeGraph()

    r1 = await index_repo(str(tmp_path), g, force=False)
    assert r1.files_added == 2

    Path(a).write_text("def f():\n\n    return 1\n", encoding="utf-8")

    r2 = await index_repo(str(tmp_path), g, force=False)
    assert r2.files_added == 0
    assert r2.files_updated == 1
    assert r2.files_skipped == 1
