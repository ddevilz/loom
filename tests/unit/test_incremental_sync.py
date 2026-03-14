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
    outgoing_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)
    incoming_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)
    outgoing_human_edges_by_path: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )
    incoming_human_edges_by_path: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict
    )

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        q = " ".join(cypher.split())

        if q == "MATCH (n {path: $path}) RETURN properties(n) AS props":
            assert params is not None
            path = params["path"]
            rows = []
            for props in self.nodes.values():
                if (
                    Path(str(props.get("path"))).as_posix()
                    == Path(str(path)).as_posix()
                ):
                    rows.append({"props": dict(props)})
            return rows

        if q == "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n":
            assert params is not None
            for node_id in params["ids"]:
                self.nodes.pop(node_id, None)
            return []

        if (
            q
            == "MATCH (n {id: $id})-[r]->() WHERE r.origin = 'human' RETURN count(r) AS c"
        ):
            assert params is not None
            return [
                {"c": self.outgoing_human_edge_count_by_node_id.get(params["id"], 0)}
            ]

        if (
            q
            == "MATCH ()-[r]->(n {id: $id}) WHERE r.origin = 'human' RETURN count(r) AS c"
        ):
            assert params is not None
            return [
                {"c": self.incoming_human_edge_count_by_node_id.get(params["id"], 0)}
            ]

        if (
            q
            == "MATCH (n {id: $id})-[r]->() WHERE r.origin = 'human' SET r.stale = true, r.stale_reason = $reason"
        ):
            return []

        if (
            q
            == "MATCH ()-[r]->(n {id: $id}) WHERE r.origin = 'human' SET r.stale = true, r.stale_reason = $reason"
        ):
            return []

        if q == "MATCH (n {path: $path}) DETACH DELETE n":
            assert params is not None
            path = params["path"]
            for node_id in [k for k, v in self.nodes.items() if v.get("path") == path]:
                self.nodes.pop(node_id, None)
            return []

        if q == "MATCH (n {path: $path}) RETURN n.id AS id":
            assert params is not None
            path = params["path"]
            return [
                {"id": node_id}
                for node_id, props in self.nodes.items()
                if Path(str(props.get("path"))).as_posix() == Path(str(path)).as_posix()
            ]

        if q.startswith("MATCH (a {path: $path})-[r]->()"):
            return []

        if (
            q
            == "MATCH ()-[r]->(a {path: $path}) WHERE r.origin IS NULL OR r.origin <> 'human' DELETE r"
        ):
            return []

        if (
            q
            == "MATCH ()-[r]->(a {path: $path}) WHERE r.origin = 'human' SET r.stale = true, r.stale_reason = 'source_changed'"
        ):
            return []

        if (
            q
            == "MATCH (a {path: $path})-[r]->(b) WHERE r.origin = 'human' RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, properties(r) AS props"
        ):
            assert params is not None
            return self.outgoing_human_edges_by_path.get(params["path"], [])

        if (
            q
            == "MATCH (a)-[r]->(b {path: $path}) WHERE r.origin = 'human' RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, properties(r) AS props"
        ):
            assert params is not None
            return self.incoming_human_edges_by_path.get(params["path"], [])

        if q.startswith("MATCH (a {id: $from_id}), (b {id: $to_id}) MERGE (a)-[r:`"):
            assert params is not None
            self.edges.append(
                {
                    "from_id": params["from_id"],
                    "to_id": params["to_id"],
                    "props": params["props"],
                }
            )
            return []

        if q == "MATCH (n {id: $id})-[:LOOM_IMPLEMENTS]->(d) RETURN d.id AS id":
            assert params is not None
            node_id = params["id"]
            return [
                {"id": doc_id} for doc_id in self.implements_by_node_id.get(node_id, [])
            ]

        if (
            q
            == "MATCH (n {id: $id})-[r]-() WHERE r.origin = 'human' RETURN count(r) AS c"
        ):
            assert params is not None
            out_c = self.outgoing_human_edge_count_by_node_id.get(params["id"], 0)
            in_c = self.incoming_human_edge_count_by_node_id.get(params["id"], 0)
            return [{"c": out_c + in_c}]

        if q == "MATCH (n) RETURN count(n) AS c":
            return [{"c": len(self.nodes)}]

        if q == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": len(self.edges)}]

        if q == "MATCH (n) WHERE n.id STARTS WITH 'doc:' RETURN properties(n) AS props":
            rows = []
            for props in self.nodes.values():
                if str(props.get("id", "")).startswith("doc:"):
                    rows.append({"props": dict(props)})
            return rows

        raise AssertionError(f"Unexpected cypher: {cypher}")

    async def bulk_create_nodes(self, nodes: list[Node]) -> None:
        for n in nodes:
            self.nodes[n.id] = n.model_dump()

    async def bulk_create_edges(self, edges) -> None:
        for e in edges:
            self.edges.append({"from_id": e.from_id, "to_id": e.to_id, "kind": e.kind})


@pytest.mark.asyncio
async def test_sync_commits_modified_file_updates_only_that_path(
    tmp_path: Path, monkeypatch
) -> None:
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
async def test_sync_commits_emits_ast_drift_warning_and_violation_edge(
    tmp_path: Path, monkeypatch
) -> None:
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


@pytest.mark.asyncio
async def test_sync_commits_modified_file_rebuilds_file_node_and_call_edges(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.py"
    p.write_text(
        "def g():\n    return 1\n\ndef f():\n    return g()\n", encoding="utf-8"
    )
    abs_path = p.resolve().as_posix()

    old_node = Node(
        id=f"function:{abs_path}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=abs_path,
        content_hash="old",
        start_line=3,
        end_line=4,
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

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert f"file:{abs_path}" in g.nodes
    assert any(edge["kind"] == EdgeType.CALLS for edge in g.edges)


@pytest.mark.asyncio
async def test_sync_commits_rename_rebuilds_file_node_and_call_edges(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = repo / "a.py"
    new_path = repo / "b.py"
    old_path.write_text(
        "def g():\n    return 1\n\ndef f():\n    return g()\n", encoding="utf-8"
    )
    old_abs = old_path.resolve().as_posix()
    new_abs = new_path.resolve().as_posix()

    old_node = Node(
        id=f"function:{old_abs}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=old_abs,
        content_hash="old-hash",
        start_line=3,
        end_line=4,
        metadata={},
    )

    g = FakeGraph(nodes={old_node.id: old_node.model_dump()})

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    old_path.rename(new_path)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert f"file:{new_abs}" in g.nodes
    assert any(edge["kind"] == EdgeType.CALLS for edge in g.edges)


@pytest.mark.asyncio
async def test_sync_commits_modified_typescript_file_rebuilds_call_edges(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.ts"
    p.write_text(
        "function g() { return 1 }\nfunction f() { return g() }\n", encoding="utf-8"
    )
    abs_path = p.resolve().as_posix()

    old_node = Node(
        id=f"function:{abs_path}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=abs_path,
        content_hash="old",
        start_line=2,
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
        return [FC("M", "a.ts")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert any(edge["kind"] == EdgeType.CALLS for edge in g.edges)


@pytest.mark.asyncio
async def test_sync_commits_modified_java_file_rebuilds_call_edges(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "A.java"
    p.write_text("class A { void b() {} void a() { b(); } }\n", encoding="utf-8")
    abs_path = p.resolve().as_posix()

    old_node = Node(
        id=f"method:{abs_path}:a",
        kind=NodeKind.METHOD,
        source=NodeSource.CODE,
        name="a",
        path=abs_path,
        content_hash="old",
        start_line=1,
        end_line=1,
        metadata={},
    )

    g = FakeGraph(nodes={old_node.id: old_node.model_dump()})

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("M", "A.java")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert any(edge["kind"] == EdgeType.CALLS for edge in g.edges)


@pytest.mark.asyncio
async def test_sync_commits_relinks_changed_code_nodes_against_existing_doc_nodes(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    abs_path = p.resolve().as_posix()

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

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump(), doc_node.id: doc_node.model_dump()}
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)

    p.write_text("def f():\n    return 2\n", encoding="utf-8")

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert not any(edge.get("kind") == EdgeType.LOOM_IMPLEMENTS for edge in g.edges)
    assert old_node.id not in g.nodes
    assert any(props.get("path") == new_path.resolve().as_posix() for props in g.nodes.values())


@pytest.mark.asyncio
async def test_sync_commits_rename_migrates_human_edge_metadata_as_dict(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = repo / "a.py"
    new_path = repo / "b.py"
    old_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    old_abs = old_path.resolve().as_posix()
    new_abs = new_path.resolve().as_posix()

    old_node = Node(
        id=f"function:{old_abs}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=old_abs,
        content_hash="same-hash",
        start_line=1,
        end_line=2,
        metadata={},
    )

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump()},
        outgoing_human_edges_by_path={
            old_abs: [
                {
                    "from_id": old_node.id,
                    "to_id": "doc:spec.md:root",
                    "rel_type": "LOOM_IMPLEMENTS",
                    "props": {"origin": "human", "metadata": '{"reviewed": true}'},
                }
            ]
        },
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    def fake_parse_code(path: str):
        return [
            Node(
                id=f"function:{new_abs}:f",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name="f",
                path=new_abs,
                content_hash="same-hash",
                start_line=1,
                end_line=2,
                metadata={},
            )
        ]

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr("loom.ingest.incremental.parse_code", fake_parse_code)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    old_path.rename(new_path)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    migrated = next(edge for edge in g.edges if edge.get("props") is not None)
    assert migrated["props"]["metadata"] == {"reviewed": True}


@pytest.mark.asyncio
async def test_sync_commits_rename_migrates_incoming_human_edge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = repo / "a.py"
    new_path = repo / "b.py"
    old_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    old_abs = old_path.resolve().as_posix()
    new_abs = new_path.resolve().as_posix()

    old_node = Node(
        id=f"function:{old_abs}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=old_abs,
        content_hash="same-hash",
        start_line=1,
        end_line=2,
        metadata={},
    )

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump()},
        incoming_human_edges_by_path={
            old_abs: [
                {
                    "from_id": "doc:spec.md:root",
                    "to_id": old_node.id,
                    "rel_type": "LOOM_IMPLEMENTS",
                    "props": {"origin": "human", "metadata": '{"reviewed": true}'},
                }
            ]
        },
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    def fake_parse_code(path: str):
        return [
            Node(
                id=f"function:{new_abs}:f",
                kind=NodeKind.FUNCTION,
                source=NodeSource.CODE,
                name="f",
                path=new_abs,
                content_hash="same-hash",
                start_line=1,
                end_line=2,
                metadata={},
            )
        ]

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr("loom.ingest.incremental.parse_code", fake_parse_code)
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    old_path.rename(new_path)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    migrated = next(edge for edge in g.edges if edge.get("props") is not None)
    assert migrated["from_id"] == "doc:spec.md:root"
    assert migrated["to_id"] == f"function:{new_abs}:f"
    assert migrated["props"]["metadata"] == {"reviewed": True}


@pytest.mark.asyncio
async def test_sync_commits_rename_migrates_human_edge_attached_to_file_node(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = repo / "a.py"
    new_path = repo / "b.py"
    old_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    old_abs = old_path.resolve().as_posix()
    new_abs = new_path.resolve().as_posix()
    file_hash = old_path.read_bytes().hex()

    old_file_node = Node(
        id=f"file:{old_abs}",
        kind=NodeKind.FILE,
        source=NodeSource.CODE,
        name="a.py",
        path=old_abs,
        content_hash=file_hash,
        metadata={},
    )

    g = FakeGraph(
        nodes={old_file_node.id: old_file_node.model_dump()},
        outgoing_human_edges_by_path={
            old_abs: [
                {
                    "from_id": old_file_node.id,
                    "to_id": "doc:spec.md:root",
                    "rel_type": "LOOM_IMPLEMENTS",
                    "props": {"origin": "human", "metadata": '{"reviewed": true}'},
                }
            ]
        },
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    async def fake_embed_nodes(nodes: list[Node]):
        return nodes

    def fake_parse_code(path: str):
        return []

    class _FakeSemanticLinker:
        async def link(
            self, code_nodes: list[Node], doc_nodes: list[Node], graph: FakeGraph
        ):
            return []

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)
    monkeypatch.setattr("loom.ingest.incremental.embed_nodes", fake_embed_nodes)
    monkeypatch.setattr("loom.ingest.incremental.parse_code", fake_parse_code)
    monkeypatch.setattr(
        "loom.ingest.incremental.content_hash_bytes", lambda _b: file_hash
    )
    monkeypatch.setattr(
        "loom.ingest.incremental.SemanticLinker", lambda: _FakeSemanticLinker()
    )

    old_path.rename(new_path)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    migrated = next(edge for edge in g.edges if edge.get("props") is not None)
    assert migrated["from_id"] == f"file:{new_abs}"
    assert migrated["to_id"] == "doc:spec.md:root"
    assert migrated["props"]["metadata"] == {"reviewed": True}


@pytest.mark.asyncio
async def test_sync_commits_preserves_node_with_incoming_human_edge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    p = repo / "a.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    abs_path = p.resolve().as_posix()

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

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump()},
        incoming_human_edge_count_by_node_id={old_node.id: 1},
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("D", "a.py")]

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0
    assert old_node.id in g.nodes


@pytest.mark.asyncio
async def test_sync_commits_relinks_renamed_code_nodes_against_existing_doc_nodes(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = repo / "a.py"
    new_path = repo / "b.py"
    old_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    old_abs = old_path.resolve().as_posix()
    new_path.resolve().as_posix()

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
        id=f"function:{old_abs}:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path=old_abs,
        content_hash="same-hash",
        start_line=1,
        end_line=2,
        metadata={},
    )

    g = FakeGraph(
        nodes={old_node.id: old_node.model_dump(), doc_node.id: doc_node.model_dump()}
    )

    class FC:
        def __init__(self, status: str, path: str, old_path: str | None = None) -> None:
            self.status = status
            self.path = path
            self.old_path = old_path

    async def fake_changed(repo_path: str, old_sha: str, new_sha: str):
        return [FC("R", "b.py", "a.py")]

    monkeypatch.setattr("loom.ingest.incremental.get_changed_files", fake_changed)

    old_path.rename(new_path)

    res = await sync_commits(str(repo), "old", "new", g)

    assert res.error_count == 0

    # Renames currently do best-effort migration of HUMAN edges only; they do not
    # re-run semantic linking to create new LOOM_IMPLEMENTS edges.
    assert not any(edge.get("kind") == EdgeType.LOOM_IMPLEMENTS for edge in g.edges)

    # Ensure old code nodes are removed and nodes for the renamed file exist.
    assert old_node.id not in g.nodes
    assert any(props.get("path") == new_path.resolve().as_posix() for props in g.nodes.values())
