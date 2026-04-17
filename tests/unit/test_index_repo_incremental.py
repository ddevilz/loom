from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loom.core import EdgeType, Node, NodeKind, NodeSource
from loom.ingest.pipeline import index_repo


@dataclass
class FakeGraph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    bulk_nodes_calls: int = 0
    edges: list[dict[str, Any]] = field(default_factory=list)

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if (
            cypher.strip()
            == "MATCH (n:File) RETURN n.id AS id, n.content_hash AS content_hash"
        ):
            return [
                {"id": node_id, "content_hash": props.get("content_hash")}
                for node_id, props in self.nodes.items()
                if props.get("kind") == "file"
            ]

        if cypher.strip() == "MATCH (n) RETURN count(n) AS c":
            return [{"c": len(self.nodes)}]

        if cypher.strip() == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": len(self.edges)}]

        if (
            cypher.strip()
            == "MATCH (n) WHERE n.id STARTS WITH 'doc:' RETURN properties(n) AS props"
        ):
            return [
                {"props": dict(props)}
                for props in self.nodes.values()
                if str(props.get("id", "")).startswith("doc:")
            ]

        if (
            cypher.strip().startswith("MATCH (a {path: $path})-[r]->()")
            or cypher.strip().startswith("MATCH ()-[r]->(a {path: $path})")
            or cypher.strip().startswith("MATCH (a {path: $path})-[r]->()")
            or cypher.strip().startswith("MATCH ()-[r]->(a {path: $path})")
        ):
            # Edge invalidation queries are accepted but ignored by this fake.
            return []

        if cypher.strip() == "MATCH (n {path: $path}) RETURN n.id AS id":
            assert params is not None
            path = params["path"]
            return [
                {"id": node_id}
                for node_id, props in self.nodes.items()
                if props.get("path") == path
            ]

        if cypher.strip() == "MATCH (n {id: $id}) DETACH DELETE n":
            assert params is not None
            node_id = params["id"]
            self.nodes.pop(node_id, None)
            return []

        if (
            cypher.strip()
            == "MATCH (n) WHERE n.path STARTS WITH $path_prefix DETACH DELETE n"
        ):
            assert params is not None
            prefix = params["path_prefix"]
            for node_id in [
                node_id
                for node_id, props in self.nodes.items()
                if str(props.get("path", "")).startswith(prefix)
            ]:
                self.nodes.pop(node_id, None)
            return []

        if cypher.strip().startswith("MERGE (m:_LoomMeta"):
            # _LoomMeta metadata write — accepted, no-op in tests
            return []

        raise AssertionError(f"Unexpected cypher: {cypher}")

    async def bulk_create_nodes(self, nodes: list[Any]) -> None:
        self.bulk_nodes_calls += 1
        for n in nodes:
            self.nodes[n.id] = n.model_dump()

    async def bulk_create_edges(self, edges: list[Any]) -> None:
        for e in edges:
            self.edges.append({"from_id": e.from_id, "to_id": e.to_id, "kind": e.kind})


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


@pytest.mark.asyncio
async def test_index_repo_force_rebuild_clears_stale_repo_nodes(tmp_path: Path) -> None:
    _write(tmp_path, "a.py", "def f():\n    return 1\n")
    stale_path = str((tmp_path / "stale.py").resolve())

    g = FakeGraph(
        nodes={
            "function:stale": {
                "id": "function:stale",
                "kind": "function",
                "path": stale_path,
                "name": "stale",
            }
        }
    )

    r = await index_repo(str(tmp_path), g, force=True)

    assert r.error_count == 0
    assert r.files_added == 1
    assert g.bulk_nodes_calls >= 1
    assert all(props.get("path") != stale_path for props in g.nodes.values())
    assert any(node_id != "function:stale" for node_id in g.nodes)


@pytest.mark.asyncio
async def test_index_repo_relinks_changed_code_nodes_against_existing_doc_nodes(
    tmp_path: Path, monkeypatch
) -> None:
    file_path = _write(tmp_path, "a.py", "def f():\n    return 1\n")
    abs_path = Path(file_path).resolve().as_posix()

    doc_node = Node(
        id="doc:spec.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Req",
        path="spec.md",
        summary="return value requirement",
        embedding=[1.0, 0.0],
        metadata={},
    )
    old_node = Node(
        id=f"function:{abs_path}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=abs_path,
        content_hash="old",
        start_line=1,
        end_line=2,
        metadata={},
    )

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            await graph.bulk_create_edges(
                [
                    type(
                        "_EdgeLike",
                        (),
                        {
                            "from_id": code_nodes[0].id,
                            "to_id": doc_nodes[0].id,
                            "kind": EdgeType.LOOM_IMPLEMENTS,
                        },
                    )()
                ]
            )
            return []

    monkeypatch.setattr(
        "loom.ingest.pipeline.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump(), doc_node.id: doc_node.model_dump()}
    )

    Path(file_path).write_text("def f():\n    return 2\n", encoding="utf-8")

    res = await index_repo(str(tmp_path), g, force=False)

    assert res.error_count == 0
    assert any(edge["kind"] == EdgeType.LOOM_IMPLEMENTS for edge in g.edges)
