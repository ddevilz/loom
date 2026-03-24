from __future__ import annotations

import pytest

from loom.core.edge import EdgeType
from loom.core.node import Node, NodeKind, NodeSource
from loom.ingest.git_miner import MiningResult
from loom.linker.ticket_linker import (
    TicketLinker,
    _is_test_node,
    link_tickets_by_git_log,
)


def _make_ticket(number: str) -> Node:
    return Node(
        id=f"ticket:github:owner/repo/{number}",
        kind=NodeKind.TICKET,
        source=NodeSource.TICKET,
        name=f"#{number}",
        path=f"github://owner/repo/{number}",
        external_id=number,
        status="open",
    )


def _make_fn(name: str, path: str = "src/auth.py") -> Node:
    return Node(
        id=f"function:{path}:{name}",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
    )


def test_is_test_node_by_path():
    node = _make_fn("test_login", "tests/test_auth.py")
    assert _is_test_node(node)


def test_is_test_node_by_name():
    node = _make_fn("test_validate_user", "src/auth.py")
    assert _is_test_node(node)


def test_is_not_test_node():
    node = _make_fn("validate_user", "src/auth.py")
    assert not _is_test_node(node)


def test_is_not_test_node_for_non_test_substrings():
    node = _make_fn("validate_user", "src/protest_handler.py")
    assert not _is_test_node(node)


def test_ticket_linker_defaults():
    linker = TicketLinker()
    assert 0 < linker.embed_threshold < 1
    assert linker.use_git_log is True


@pytest.mark.asyncio
async def test_link_empty_inputs():
    linker = TicketLinker()
    result = await linker.link([], [])
    assert result == []


@pytest.mark.asyncio
async def test_link_filters_non_ticket_nodes():
    """Non-ticket nodes in ticket_nodes list are silently filtered."""
    linker = TicketLinker()
    doc_node = Node(
        id="doc:specs/auth.md:section1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Authentication",
        path="specs/auth.md",
    )
    fn = _make_fn("validate_user")
    # Should not crash even though doc_node is not a ticket
    result = await linker.link([doc_node], [fn])
    assert result == []  # doc_node filtered out, no ticket nodes remain


def test_git_log_creates_realizes_edges():
    """Git log mining should create REALIZES edges from code to ticket."""
    ticket = _make_ticket("42")
    fn = _make_fn("validate_user", "src/auth.py")

    mining = MiningResult()
    mining.file_to_tickets["src/auth.py"] = {"#42"}
    mining.ticket_to_files["#42"] = {"src/auth.py"}

    edges = link_tickets_by_git_log([ticket], [fn], mining)

    # Should have at least one REALIZES edge
    realizes_edges = [e for e in edges if e.kind == EdgeType.REALIZES]
    assert len(realizes_edges) >= 1
    assert realizes_edges[0].from_id == fn.id
    assert realizes_edges[0].to_id == ticket.id
    assert realizes_edges[0].link_method == "git_log"


def test_git_log_creates_verified_by_for_tests():
    """Git log mining should create VERIFIED_BY edges for test nodes."""
    ticket = _make_ticket("42")
    test_fn = _make_fn("test_validate_user", "tests/test_auth.py")

    mining = MiningResult()
    mining.file_to_tickets["tests/test_auth.py"] = {"#42"}
    mining.ticket_to_files["#42"] = {"tests/test_auth.py"}

    edges = link_tickets_by_git_log([ticket], [test_fn], mining)

    verified_edges = [e for e in edges if e.kind == EdgeType.VERIFIED_BY]
    assert len(verified_edges) >= 1
    assert verified_edges[0].from_id == ticket.id
    assert verified_edges[0].to_id == test_fn.id


def test_git_log_no_edges_when_no_overlap():
    """If ticket ref doesn't match any known file, no edges created."""
    ticket = _make_ticket("42")
    fn = _make_fn("validate_user", "src/auth.py")

    mining = MiningResult()
    # No overlap between ticket refs and code files
    mining.file_to_tickets["other_file.py"] = {"#99"}

    edges = link_tickets_by_git_log([ticket], [fn], mining)
    assert edges == []
