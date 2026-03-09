from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loom.core import EdgeType
from loom.ingest.incremental import sync_commits


def _git(cwd: str, *args: str) -> str:
    p = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return p.stdout


@dataclass
class FakeGraph:
    nodes_by_path: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    outgoing_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)
    incoming_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)
    implements_by_node_id: dict[str, list[str]] = field(default_factory=dict)

    node_deletes: int = 0
    bulk_upserts: int = 0
    persisted_edges: list[dict[str, Any]] = field(default_factory=list)
    invalidated_paths: list[str] = field(default_factory=list)

    async def query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        q = cypher.strip()

        if q == "MATCH (n {path: $path}) RETURN properties(n) AS props":
            assert params is not None
            path = params["path"]
            rows: list[dict[str, Any]] = []
            for stored_path, props_list in self.nodes_by_path.items():
                if Path(str(stored_path)).as_posix() == Path(str(path)).as_posix():
                    rows.extend({"props": dict(p)} for p in props_list)
            return rows

        if (
            q
            == "MATCH (n {id: $id})-[r]->()\nWHERE r.origin = 'human'\nRETURN count(r) AS c"
        ):
            assert params is not None
            node_id = params["id"]
            return [{"c": self.outgoing_human_edge_count_by_node_id.get(node_id, 0)}]

        if (
            q
            == "MATCH ()-[r]->(n {id: $id})\nWHERE r.origin = 'human'\nRETURN count(r) AS c"
        ):
            assert params is not None
            node_id = params["id"]
            return [{"c": self.incoming_human_edge_count_by_node_id.get(node_id, 0)}]

        if (
            q
            == "MATCH (n {id: $id})-[r]->()\nWHERE r.origin = 'human'\nSET r.stale = true,\n    r.stale_reason = $reason"
        ):
            return []

        if (
            q
            == "MATCH ()-[r]->(n {id: $id})\nWHERE r.origin = 'human'\nSET r.stale = true,\n    r.stale_reason = $reason"
        ):
            return []

        if q == "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n":
            assert params is not None
            self.node_deletes += len(params["ids"])
            return []

        if q.startswith("MATCH (a {path: $path})-[r]->()"):
            if params is not None:
                self.invalidated_paths.append(params["path"])
            return []

        if (
            q
            == "MATCH ()-[r]->(a {path: $path})\nWHERE r.origin IS NULL OR r.origin <> 'human'\nDELETE r"
        ):
            if params is not None:
                self.invalidated_paths.append(params["path"])
            return []

        if (
            q
            == "MATCH ()-[r]->(a {path: $path})\nWHERE r.origin = 'human'\nSET r.stale = true,\n    r.stale_reason = 'source_changed'"
        ):
            if params is not None:
                self.invalidated_paths.append(params["path"])
            return []

        if q == "MATCH (n {id: $id})-[:LOOM_IMPLEMENTS]->(d) RETURN d.id AS id":
            assert params is not None
            node_id = params["id"]
            return [
                {"id": doc_id} for doc_id in self.implements_by_node_id.get(node_id, [])
            ]

        if q == "MATCH (n) RETURN count(n) AS c":
            # Not authoritative; just say 0
            return [{"c": 0}]

        if q == "MATCH ()-[r]->() RETURN count(r) AS c":
            return [{"c": len(self.persisted_edges)}]

        if "RETURN a.id AS from_id" in q and "WHERE r.origin = 'human'" in q:
            return []

        if "MERGE (a)-[r:`" in q:
            return []

        if q == "MATCH (n {path: $path}) RETURN n.id AS id":
            return []

        if q == "MATCH (n {path: $path}) DETACH DELETE n":
            self.node_deletes += 1
            return []

        raise AssertionError(f"Unexpected cypher: {cypher}")

    async def bulk_create_nodes(self, nodes) -> None:
        self.bulk_upserts += 1

    async def bulk_create_edges(self, edges) -> None:
        for e in edges:
            self.persisted_edges.append(
                {"from_id": e.from_id, "to_id": e.to_id, "kind": e.kind}
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_commits_touches_only_changed_files(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "test@example.com")
    _git(str(repo), "config", "user.name", "Test")

    (repo / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (repo / "b.py").write_text("def g():\n    return 1\n", encoding="utf-8")

    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "init")

    old = _git(str(repo), "rev-parse", "HEAD").strip()

    # modify only a.py
    (repo / "a.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(str(repo), "add", "a.py")
    _git(str(repo), "commit", "-m", "change a")

    new = _git(str(repo), "rev-parse", "HEAD").strip()

    # Pre-seed graph with nodes for both paths; only a.py should be queried/updated.
    a_abs = str((repo / "a.py").resolve())
    b_abs = str((repo / "b.py").resolve())

    g = FakeGraph(
        nodes_by_path={
            a_abs: [
                {
                    "id": f"function:{a_abs}:f",
                    "kind": "function",
                    "source": "code",
                    "name": "f",
                    "path": a_abs,
                    "content_hash": "old",
                    "metadata": {},
                }
            ],
            b_abs: [
                {
                    "id": f"function:{b_abs}:g",
                    "kind": "function",
                    "source": "code",
                    "name": "g",
                    "path": b_abs,
                    "content_hash": "old",
                    "metadata": {},
                }
            ],
        }
    )

    res = await sync_commits(str(repo), old, new, g)

    assert res.file_count == 1
    assert res.files_updated == 1
    assert res.files_added == 0
    assert res.files_deleted == 0
    assert g.bulk_upserts >= 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_commits_end_to_end_emits_drift_warning_and_violation_edge(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "test@example.com")
    _git(str(repo), "config", "user.name", "Test")

    file_path = repo / "a.py"
    file_path.write_text("def f(x, y):\n    return x + y\n", encoding="utf-8")

    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "init")
    old = _git(str(repo), "rev-parse", "HEAD").strip()

    file_path.write_text("def f(x):\n    return str(x)\n", encoding="utf-8")
    _git(str(repo), "add", "a.py")
    _git(str(repo), "commit", "-m", "change a")
    new = _git(str(repo), "rev-parse", "HEAD").strip()

    abs_path = file_path.resolve().as_posix()
    old_node_id = f"function:{abs_path}:f"
    g = FakeGraph(
        nodes_by_path={
            abs_path: [
                {
                    "id": old_node_id,
                    "kind": "function",
                    "source": "code",
                    "name": "f",
                    "path": abs_path,
                    "content_hash": "old",
                    "metadata": {
                        "signature": "f(x, y)",
                        "params": ["x", "y"],
                        "return_type": None,
                    },
                }
            ]
        },
        implements_by_node_id={old_node_id: ["doc:spec.md:s1"]},
    )

    res = await sync_commits(str(repo), old, new, g)

    assert res.files_updated == 1
    assert res.warnings
    assert any("AST drift detected" in warning for warning in res.warnings)
    assert any(edge["kind"] == EdgeType.LOOM_VIOLATES for edge in g.persisted_edges)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_commits_delete_preserves_node_with_incoming_human_edge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(str(repo), "init")
    _git(str(repo), "config", "user.email", "test@example.com")
    _git(str(repo), "config", "user.name", "Test")

    file_path = repo / "a.py"
    file_path.write_text("def f():\n    return 1\n", encoding="utf-8")

    _git(str(repo), "add", ".")
    _git(str(repo), "commit", "-m", "init")
    old = _git(str(repo), "rev-parse", "HEAD").strip()

    _git(str(repo), "rm", "a.py")
    _git(str(repo), "commit", "-m", "delete a")
    new = _git(str(repo), "rev-parse", "HEAD").strip()

    abs_path = file_path.resolve().as_posix()
    node_id = f"function:{abs_path}:f"
    g = FakeGraph(
        nodes_by_path={
            abs_path: [
                {
                    "id": node_id,
                    "kind": "function",
                    "source": "code",
                    "name": "f",
                    "path": abs_path,
                    "content_hash": "old",
                    "metadata": {},
                }
            ]
        },
        incoming_human_edge_count_by_node_id={node_id: 1},
    )

    res = await sync_commits(str(repo), old, new, g)

    assert res.files_deleted == 1
    assert g.node_deletes == 0
    assert g.invalidated_paths == [abs_path, abs_path, abs_path, abs_path]
