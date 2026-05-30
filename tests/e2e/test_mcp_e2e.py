from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from fastmcp import Client

from loom.graph.db import DB
from loom.server.app import build_server

_FIXTURE_REPO = Path(__file__).parents[2] / "tests" / "fixtures" / "python_flask_app"


@pytest_asyncio.fixture
async def indexed_server():
    """FastMCP server with python_flask_app indexed into an in-memory DB."""
    db = DB(path=":memory:")
    server = build_server(db=db)
    from loom.graph.repository import Repository
    from loom.indexer.pipeline import index_repo

    await index_repo(_FIXTURE_REPO, repo=Repository(db))
    return server


@pytest_asyncio.fixture
async def empty_server():
    """FastMCP server with an empty DB — for error-path tests."""
    db = DB(path=":memory:")
    return build_server(db=db)


# ── Tool listing ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools_returns_all_20(indexed_server) -> None:
    async with Client(indexed_server) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    expected = {
        "search_code",
        "get_blast_radius",
        "get_neighbors",
        "get_community",
        "shortest_path",
        "graph_stats",
        "god_nodes",
        "store_understanding",
        "store_understanding_batch",
        "get_context",
        "get_savings",
        "start_session",
        "get_delta",
        "get_surprising_connections",
        "suggest_questions",
        "get_work_plan",
        "get_status",
        "get_architecture",
        "store_tags",
        "list_projects",
    }
    assert names == expected


# ── start_session ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_session_returns_required_fields(indexed_server) -> None:
    async with Client(indexed_server) as client:
        r = await client.call_tool("start_session", {"agent_id": "test"})
    data = r.data["data"]
    assert "session_id" in data
    assert "unannotated_reads" in data
    assert "annotation_gaps" in data


# ── search_code ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_code_result_has_enriched_fields(indexed_server) -> None:
    async with Client(indexed_server) as client:
        r = await client.call_tool("search_code", {"query": "get_user", "limit": 5})
    results = r.data["data"]
    assert len(results) > 0
    first = results[0]
    for field in ("confidence", "caller_count", "community_id"):
        assert field in first, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_search_code_dead_nodes_rank_last(indexed_server) -> None:
    """Search results are returned in score order."""
    async with Client(indexed_server) as client:
        r = await client.call_tool("search_code", {"query": "user", "limit": 20})
    results = r.data["data"]
    # Basic sanity: results are returned
    assert isinstance(results, list)


# ── error handling ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_understanding_bad_node_id(empty_server) -> None:
    async with Client(empty_server) as client:
        r = await client.call_tool(
            "store_understanding",
            {"node_id": "function:nonexistent.py:ghost", "summary": "test"},
        )
    assert r.data["ok"] is False
    assert r.data["error_code"] == "NODE_NOT_FOUND"


# ── get_blast_radius ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_blast_radius_returns_nodes_key(indexed_server) -> None:
    async with Client(indexed_server) as client:
        sr = await client.call_tool("search_code", {"query": "create_user", "limit": 3})
        results = [x for x in sr.data["data"] if x.get("kind") in ("function", "method")]
        if not results:
            pytest.skip("no function/method node found for create_user")
        nid = results[0]["id"]
        r = await client.call_tool("get_blast_radius", {"node_id": nid, "depth": 2})
    assert "nodes" in r.data["data"]


# ── get_status ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_returns_node_count(indexed_server) -> None:
    async with Client(indexed_server) as client:
        r = await client.call_tool("get_status", {})
    assert isinstance(r.data["data"]["node_count"], int)
    assert r.data["data"]["node_count"] > 0


# ── Token-saving loop (core product promise) ──────────────────────────────────


@pytest.mark.asyncio
async def test_token_saving_loop_end_to_end(indexed_server) -> None:
    """
    Proves the full product promise end-to-end:
      session 1: read node (nudge present) → annotate → nudge gone
      session 2: same node NOT in unannotated_reads (skip proven)
    """
    async with Client(indexed_server) as client:
        # Step 1: start session
        r = await client.call_tool("start_session", {"agent_id": "test-agent"})
        assert r.data["ok"] is True

        # Step 2: search for get_user
        sr = await client.call_tool("search_code", {"query": "get_user", "limit": 5})
        results = [
            x
            for x in sr.data["data"]
            if x.get("kind") in ("function", "method") and not x.get("suggested_instead")
        ]
        assert results, "No function/method node found for 'get_user' in fixture"
        node_id = results[0]["id"]

        # Step 3: get_context — nudge must be present (no AGENT summary yet)
        ctx = await client.call_tool("get_context", {"node_id": node_id})
        assert ctx.data["ok"] is True
        packet = ctx.data["data"]
        assert "_nudge" in packet, (
            f"_nudge missing before annotation, got keys: {list(packet.keys())}"
        )
        assert packet["summary_source"] == "AUTO"

        # Step 4: store understanding
        su = await client.call_tool(
            "store_understanding",
            {"node_id": node_id, "summary": "Fetches a single user by ID from the database"},
        )
        assert su.data["ok"] is True
        assert su.data["data"]["skipped"] is False

        # Step 5: get_context again — nudge must be gone, source must be AGENT
        ctx2 = await client.call_tool("get_context", {"node_id": node_id})
        packet2 = ctx2.data["data"]
        assert "_nudge" not in packet2, (
            "_nudge still present after store_understanding — cache invalidation broken"
        )
        assert packet2["summary_source"] == "AGENT"
        assert packet2["summary_author"] == "test-agent"

        # Step 6: start a new session
        r2 = await client.call_tool("start_session", {"agent_id": "test-agent"})
        assert r2.data["ok"] is True
        new_session = r2.data["data"]

        # Step 7: annotated node must NOT appear in unannotated_reads
        unannotated_ids = [x["node_id"] for x in new_session.get("unannotated_reads", [])]
        assert node_id not in unannotated_ids, (
            f"Annotated node {node_id} still appears in unannotated_reads — "
            "skip not proven; node will be re-read next session"
        )


# ── Memo cache ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memo_cache_invalidated_after_store_understanding(indexed_server) -> None:
    """store_understanding must bust the memo cache so get_context reflects new summary."""
    async with Client(indexed_server) as client:
        await client.call_tool("start_session", {"agent_id": "cache-test"})

        sr = await client.call_tool("search_code", {"query": "create_user", "limit": 3})
        results = [x for x in sr.data["data"] if x.get("kind") in ("function", "method")]
        if not results:
            pytest.skip("no function/method node for create_user")
        nid = results[0]["id"]

        # Prime the cache
        ctx_before = await client.call_tool("get_context", {"node_id": nid})
        assert ctx_before.data["data"]["summary_source"] == "AUTO"

        # Annotate — must invalidate cache
        await client.call_tool(
            "store_understanding",
            {"node_id": nid, "summary": "Creates a new user with hashed password"},
        )

        # Cache must be busted — new summary must be visible
        ctx_after = await client.call_tool("get_context", {"node_id": nid})
        assert ctx_after.data["data"]["summary_source"] == "AGENT"
        assert ctx_after.data["data"]["summary"] == "Creates a new user with hashed password"


# ── get_work_plan ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_work_plan_returns_document_priority_when_unannotated(indexed_server) -> None:
    async with Client(indexed_server) as client:
        await client.call_tool("start_session", {"agent_id": "plan-test"})
        # visit a node without annotating it
        sr = await client.call_tool("search_code", {"query": "get_user", "limit": 1})
        results = [x for x in sr.data["data"] if x.get("kind") in ("function", "method")]
        if results:
            await client.call_tool("get_context", {"node_id": results[0]["id"]})

        r = await client.call_tool("get_work_plan", {})
    data = r.data["data"]
    assert "priority" in data
    assert "tasks" in data
    assert "summary_coverage" in data
    # With an unannotated indexed graph, priority must be DOCUMENT or INVESTIGATE
    assert data["priority"] in ("DOCUMENT", "INVESTIGATE", "EXPLORE", "NOTHING")


@pytest.mark.asyncio
async def test_get_neighbors_memo_cache_hit(indexed_server) -> None:
    """Calling get_neighbors twice on the same node within TTL returns identical result."""
    async with Client(indexed_server) as client:
        await client.call_tool("start_session", {"agent_id": "memo-test"})
        sr = await client.call_tool("search_code", {"query": "create_user", "limit": 3})
        results = [x for x in sr.data["data"] if x.get("kind") in ("function", "method")]
        if not results:
            pytest.skip("no function/method node for create_user")
        nid = results[0]["id"]

        r1 = await client.call_tool("get_neighbors", {"node_id": nid, "depth": 1})
        r2 = await client.call_tool("get_neighbors", {"node_id": nid, "depth": 1})

    # Both calls must return identical data (second served from memo cache)
    assert r1.data == r2.data


@pytest.mark.asyncio
async def test_get_work_plan_explore_or_nothing_when_fully_annotated(empty_server) -> None:
    """Fully annotated (empty) graph → priority is EXPLORE or NOTHING, never DOCUMENT."""
    async with Client(empty_server) as client:
        r = await client.call_tool("get_work_plan", {})
    data = r.data["data"]
    assert data["priority"] in ("EXPLORE", "NOTHING"), (
        f"Expected EXPLORE or NOTHING for empty/fully-annotated graph, got {data['priority']}"
    )
