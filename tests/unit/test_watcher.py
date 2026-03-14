from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from watchfiles import Change

from loom.watch.watcher import watch_repo


@dataclass
class _FakeGraph:
    queries: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    ids_by_path: dict[str, list[str]] = field(default_factory=dict)
    outgoing_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)
    incoming_human_edge_count_by_node_id: dict[str, int] = field(default_factory=dict)

    async def query(self, cypher: str, params: dict[str, Any] | None = None):
        self.queries.append((cypher, params))
        q = cypher.strip()
        if q == "MATCH (n {path: $path}) RETURN n.id AS id":
            assert params is not None
            return [
                {"id": node_id} for node_id in self.ids_by_path.get(params["path"], [])
            ]
        if (
            q
            == "MATCH (n {id: $id})-[r]->()\nWHERE r.origin = 'human'\nRETURN count(r) AS c"
        ):
            assert params is not None
            return [
                {"c": self.outgoing_human_edge_count_by_node_id.get(params["id"], 0)}
            ]
        if (
            q
            == "MATCH ()-[r]->(n {id: $id})\nWHERE r.origin = 'human'\nRETURN count(r) AS c"
        ):
            assert params is not None
            return [
                {"c": self.incoming_human_edge_count_by_node_id.get(params["id"], 0)}
            ]
        if (
            q
            == "MATCH (n {id: $id})-[r]-()\nWHERE r.origin = 'human'\nRETURN count(r) AS c"
        ):
            assert params is not None
            out_c = self.outgoing_human_edge_count_by_node_id.get(params["id"], 0)
            in_c = self.incoming_human_edge_count_by_node_id.get(params["id"], 0)
            return [{"c": out_c + in_c}]
        return []


@pytest.mark.asyncio
async def test_watch_repo_reindexes_on_file_change(tmp_path: Path) -> None:
    seen: list[tuple[str, list[str], int]] = []

    async def fake_events(_path: str):
        yield {(Change.modified, str(tmp_path / "a.py"))}

    async def fake_indexer(repo_path: str, changed_paths: list[str], graph) -> object:
        seen.append((repo_path, changed_paths, len(graph.queries)))
        return object()

    graph = _FakeGraph()
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        indexer=fake_indexer,
        stop_after_events=1,
    )

    assert seen == [(str(tmp_path), [(tmp_path / "a.py").resolve().as_posix()], 1)]
    loom_queries = [q[0] for q in graph.queries if "LOOM_IMPLEMENTS" in q[0]]
    assert len(loom_queries) == 1
    assert any(
        "MATCH (n {path: $path})-[r:LOOM_IMPLEMENTS]-()" in q for q in loom_queries
    )


@pytest.mark.asyncio
async def test_watch_repo_flags_modified_file_edges_before_reindex(
    tmp_path: Path,
) -> None:
    call_order: list[str] = []

    async def fake_events(_path: str):
        yield {(Change.modified, str(tmp_path / "a.py"))}

    @dataclass
    class _TrackingGraph(_FakeGraph):
        async def query(self, cypher: str, params: dict[str, Any] | None = None):
            if "LOOM_IMPLEMENTS" in cypher:
                call_order.append("flag")
            return await super().query(cypher, params)

    async def fake_indexer(repo_path: str, changed_paths: list[str], graph) -> object:
        assert changed_paths == [(tmp_path / "a.py").resolve().as_posix()]
        call_order.append("index")
        return object()

    graph = _TrackingGraph()
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        indexer=fake_indexer,
        stop_after_events=1,
    )

    assert call_order == ["flag", "index"]


@pytest.mark.asyncio
async def test_watch_repo_deletes_nodes_on_removed_file(tmp_path: Path) -> None:
    async def fake_events(_path: str):
        yield {(Change.deleted, str(tmp_path / "gone.py"))}

    abs_path = (tmp_path / "gone.py").resolve().as_posix()
    graph = _FakeGraph(ids_by_path={abs_path: ["function:gone"]})
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        stop_after_events=1,
    )

    assert any("DETACH DELETE" in q[0] for q in graph.queries)
    loom_queries = [i for i, q in enumerate(graph.queries) if "LOOM_IMPLEMENTS" in q[0]]
    delete_index = next(
        i for i, q in enumerate(graph.queries) if "DETACH DELETE" in q[0]
    )
    assert len(loom_queries) == 1
    assert all(index < delete_index for index in loom_queries)


@pytest.mark.asyncio
async def test_watch_repo_preserves_deleted_nodes_with_human_edges(
    tmp_path: Path,
) -> None:
    async def fake_events(_path: str):
        yield {(Change.deleted, str(tmp_path / "gone.py"))}

    abs_path = (tmp_path / "gone.py").resolve().as_posix()
    node_id = "function:gone"
    graph = _FakeGraph(
        ids_by_path={abs_path: [node_id]},
        incoming_human_edge_count_by_node_id={node_id: 1},
    )
    await watch_repo(
        str(tmp_path),
        graph,
        watcher_factory=fake_events,
        stop_after_events=1,
    )

    stale_queries = [q for q, _ in graph.queries if "stale_reason = $reason" in q]
    delete_by_ids_queries = [
        params
        for q, params in graph.queries
        if q.strip() == "UNWIND $ids AS id MATCH (n {id: id}) DETACH DELETE n"
    ]
    invalidation_queries = [
        params
        for q, params in graph.queries
        if q.strip().startswith("MATCH (n {path: $path})-[r:LOOM_IMPLEMENTS]-()")
        or q.strip()
        == "MATCH ()-[r]->(a {path: $path})\nWHERE r.origin IS NULL OR r.origin <> 'human'\nDELETE r"
        or q.strip()
        == "MATCH ()-[r]->(a {path: $path})\nWHERE r.origin = 'human'\nSET r.stale = true,\n    r.stale_reason = 'source_changed'"
    ]

    assert len(stale_queries) == 2
    assert delete_by_ids_queries == []
    assert invalidation_queries == [
        {"path": abs_path},
        {"path": abs_path},
        {"path": abs_path},
    ]
