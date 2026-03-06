from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.ingest.incremental import sync_commits


@dataclass
class FakeGraph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    implements_by_node_id: dict[str, list[str]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)

    async def query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        q = cypher.strip()

        if q == "MATCH (n {path: $path}) RETURN properties(n) AS props":
            assert params is not None
            path = params["path"]
            rows = []
            for props in self.nodes.values():
                if Path(str(props.get("path"))).as_posix() == Path(str(path)).as_posix():
                    rows.append({"props": dict(props)})
            return rows

        if q == "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n":
            assert params is not None
            for node_id in params["ids"]:
                self.nodes.pop(node_id, None)
            return []

        if q == "MATCH (n {id: $id})-[r]->()\nWHERE r.origin = 'human'\nRETURN count(r) AS c":
            return [{"c": 0}]

        if q == "MATCH (n {id: $id})-[r]->()\nWHERE r.origin = 'human'\nSET r.stale = true,\n    r.stale_reason = $reason":
            return []

        if q == "MATCH (n {path: $path}) DETACH DELETE n":
            assert params is not None
            path = params["path"]
            for node_id in [k for k, v in self.nodes.items() if v.get("path") == path]:
                self.nodes.pop(node_id, None)
            return []

        if q.startswith("MATCH (a {path: $path})-[r]->()"):
            return []

        if q == "MATCH (n {id: $id})-[:LOOM_IMPLEMENTS]->(d) RETURN d.id AS id":
            assert params is not None
            node_id = params["id"]
            return [{"id": doc_id} for doc_id in self.implements_by_node_id.get(node_id, [])]

        if q == "MATCH (n) RETURN count(n) AS c":
            return [{"c": len(self.nodes)}]

        if q == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": len(self.edges)}]

        raise AssertionError(f"Unexpected cypher: {cypher}")

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        for n in nodes:
            self.nodes[n.id] = n.model_dump()

    async def bulk_create_edges(self, edges) -> None:
        for e in edges:
            self.edges.append({"from_id": e.from_id, "to_id": e.to_id, "kind": e.kind})


@pytest.mark.asyncio
async def test_sync_commits_modified_file_updates_only_that_path(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.py"

    p.write_text("def f():\n    return 1\n", encoding="utf-8")

    abs_path = str(p)

    # Pre-seed graph with an old node for this file
    old_node = Node(
        id="function:" + abs_path + ":f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=abs_path,
        content_hash="old",
        start_line=1,
        end_line=2,
        metadata={},
    )

    g = FakeGraph(nodes={old_node.id: old_node.model_dump()})

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("M", "a.py")]

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)

    # Modify file so parse_code produces different content_hash
    p.write_text("def f():\n    return 2\n", encoding="utf-8")

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.files_updated == 1
    assert res.files_added == 0
    assert res.files_deleted == 0
    assert res.node_count >= 1


@pytest.mark.asyncio
async def test_sync_commits_emits_ast_drift_warning_and_violation_edge(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.py"

    p.write_text("def f(x, y):\n    return x + y\n", encoding="utf-8")
    abs_path = p.resolve().as_posix()

    old_node = Node(
        id="function:" + abs_path + ":f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=abs_path,
        content_hash="old",
        start_line=1,
        end_line=2,
        metadata={
            "signature": "f(x, y)",
            "params": ["x", "y"],
            "return_type": None,
        },
    )

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump()},
        implements_by_node_id={old_node.id: ["doc:spec.md:s1"]},
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("M", "a.py")]

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)

    p.write_text("def f(x):\n    return str(x)\n", encoding="utf-8")

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.warnings
    assert any("AST drift detected" in warning for warning in res.warnings)
    assert any(edge["kind"] == EdgeType.LOOM_VIOLATES for edge in g.edges)
