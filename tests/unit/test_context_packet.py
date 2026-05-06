# tests/unit/test_context_packet.py
from __future__ import annotations

import pytest

from loom.core.context import DB
from loom.core.node import Node, NodeKind, NodeSource
from loom.query.context import get_context_packet
from loom.store import nodes as node_store


def _fn(path: str, name: str, summary: str | None = None, summary_hash: str | None = None) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash",
        content_hash="contenthash1",
        summary=summary,
        summary_hash=summary_hash,
    )


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


@pytest.mark.asyncio
async def test_summary_source_agent_when_hash_set(db: DB) -> None:
    """summary_source == AGENT only when summary_hash is non-null (set via update_summary)."""
    node = _fn("a.py", "fn")
    await node_store.bulk_upsert_nodes(db, [node])
    # Simulate agent writing a summary — sets summary_hash = content_hash in DB
    await node_store.update_summary(db, node.id, "Does X.", force=True)
    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert packet["summary_source"] == "AGENT"


@pytest.mark.asyncio
async def test_summary_source_auto_when_no_hash(db: DB) -> None:
    """summary_source == AUTO when summary_hash is null (even if summary text exists)."""
    node = _fn("a.py", "fn", summary="Auto-generated text.", summary_hash=None)
    await node_store.bulk_upsert_nodes(db, [node])
    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert packet["summary_source"] == "AUTO"


@pytest.mark.asyncio
async def test_summary_source_auto_when_no_summary(db: DB) -> None:
    node = _fn("a.py", "fn")
    await node_store.bulk_upsert_nodes(db, [node])
    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert packet["summary_source"] == "AUTO"
