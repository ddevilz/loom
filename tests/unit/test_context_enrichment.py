# tests/unit/test_context_enrichment.py
from __future__ import annotations

import time

import pytest

from loom.core.context import DB
from loom.core.enums import SummarySource
from loom.core.node import Node, NodeKind, NodeSource
from loom.query.context import _compute_suggestion, _humanize_ago, get_context_packet
from loom.store import nodes as node_store

# ── _humanize_ago ────────────────────────────────────────────────────────────

def test_humanize_ago_just_now() -> None:
    assert _humanize_ago(int(time.time()) - 10) == "just now"


def test_humanize_ago_minutes() -> None:
    assert _humanize_ago(int(time.time()) - 23 * 60) == "23m"


def test_humanize_ago_hours() -> None:
    assert _humanize_ago(int(time.time()) - 2 * 3600) == "2h"


def test_humanize_ago_days() -> None:
    assert _humanize_ago(int(time.time()) - 3 * 86400) == "3d"


def test_humanize_ago_none_when_no_ts() -> None:
    assert _humanize_ago(None) is None


# ── _compute_suggestion ──────────────────────────────────────────────────────

def test_suggestion_stale_wins_over_all() -> None:
    """summary_stale is highest priority."""
    s = _compute_suggestion(
        stale=True,
        summary_source=SummarySource.AUTO,
        in_degree=10,
        edge_coverage=0.1,
        updated_at=int(time.time()) - 3 * 86400,
    )
    assert s == "Source changed — re-read and call store_understanding(force=True)"


def test_suggestion_auto_high_traffic() -> None:
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AUTO,
        in_degree=6,
        edge_coverage=1.0,
        updated_at=int(time.time()),
    )
    assert s == "High-traffic function with only auto-summary — write agent summary"


def test_suggestion_auto_low_traffic_no_match() -> None:
    """AUTO + in_degree <= 5 — no suggestion from this rule."""
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AUTO,
        in_degree=5,
        edge_coverage=1.0,
        updated_at=int(time.time()),
    )
    assert s is None


def test_suggestion_agent_no_traffic_suggestion() -> None:
    """AGENT summary never triggers auto-summary suggestion."""
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT,
        in_degree=10,
        edge_coverage=1.0,
        updated_at=int(time.time()),
    )
    assert s is None


def test_suggestion_low_edge_coverage() -> None:
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT,
        in_degree=1,
        edge_coverage=0.3,
        updated_at=int(time.time()),
    )
    assert s == "Call graph incomplete (dynamic dispatch) — callers list may be missing entries"


def test_suggestion_edge_coverage_unknown_no_match() -> None:
    """'unknown' edge_coverage does not trigger rule 3."""
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT,
        in_degree=1,
        edge_coverage="unknown",
        updated_at=int(time.time()),
    )
    assert s is None


def test_suggestion_old_index() -> None:
    old_ts = int(time.time()) - 49 * 3600  # 49 hours ago
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT,
        in_degree=1,
        edge_coverage=1.0,
        updated_at=old_ts,
    )
    assert s == "Index is 2+ days old — run: loom analyze ."


def test_suggestion_none_when_nothing_triggers() -> None:
    s = _compute_suggestion(
        stale=False,
        summary_source=SummarySource.AGENT,
        in_degree=2,
        edge_coverage=0.9,
        updated_at=int(time.time()),
    )
    assert s is None


# ── Integration: get_context_packet fields ───────────────────────────────────


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


def _fn(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash",
        content_hash="contenthash1",
    )


def _cls(path: str, name: str) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.CLASS, path, name),
        kind=NodeKind.CLASS,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="hash",
        content_hash="contenthash1",
    )


@pytest.mark.asyncio
async def test_get_context_packet_has_enriched_fields(db: DB) -> None:
    """get_context_packet returns last_analyzed_ago and suggestion fields."""
    node = _fn("src/auth.py", "validate_token")
    await node_store.bulk_upsert_nodes(db, [node])

    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert "last_analyzed_ago" in packet
    assert "suggestion" in packet
    # Freshly indexed node — last_analyzed_ago should be "just now"
    assert packet["last_analyzed_ago"] == "just now"


@pytest.mark.asyncio
async def test_get_context_packet_members_has_enriched_fields(db: DB) -> None:
    """_build_members_packet (class node) also returns last_analyzed_ago and suggestion."""
    node = _cls("src/models.py", "User")
    await node_store.bulk_upsert_nodes(db, [node])

    packet = await get_context_packet(db, node.id)
    assert packet is not None
    assert "last_analyzed_ago" in packet
    assert "suggestion" in packet
    assert packet["last_analyzed_ago"] == "just now"
