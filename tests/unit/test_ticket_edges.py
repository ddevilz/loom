from __future__ import annotations

import pytest
from pydantic import ValidationError

from loom.core.edge import Edge, EdgeType, EdgeOrigin
from loom.core.falkor.edge_type_adapter import EdgeTypeAdapter


def test_new_edge_types_exist():
    assert EdgeType.REALIZES == "realizes"
    assert EdgeType.CLOSES == "closes"
    assert EdgeType.VERIFIED_BY == "verified_by"
    assert EdgeType.DEPENDS_ON == "depends_on"


def test_realizes_edge_is_loom_edge():
    e = Edge(
        from_id="function:src/auth.py:validate",
        to_id="ticket:github:owner/repo/42",
        kind=EdgeType.REALIZES,
        link_method="git_log",
        link_reason="commit abc closes #42",
        confidence=0.9,
    )
    assert e.is_loom_edge


def test_closes_edge_is_loom_edge():
    e = Edge(
        from_id="function:src/auth.py:validate",
        to_id="ticket:jira:PROJ/PROJ-1",
        kind=EdgeType.CLOSES,
        link_method="ticket_ref",
        confidence=0.95,
    )
    assert e.is_loom_edge


def test_verified_by_edge():
    e = Edge(
        from_id="ticket:github:owner/repo/42",
        to_id="function:tests/test_auth.py:test_login",
        kind=EdgeType.VERIFIED_BY,
        link_method="embed_match",
        confidence=0.8,
    )
    assert e.is_loom_edge


def test_depends_on_edge():
    e = Edge(
        from_id="ticket:github:owner/repo/42",
        to_id="ticket:github:owner/repo/10",
        kind=EdgeType.DEPENDS_ON,
        confidence=1.0,
    )
    assert e.is_loom_edge


def test_git_log_link_method():
    e = Edge(
        from_id="function:src/x.py:foo",
        to_id="ticket:github:owner/repo/1",
        kind=EdgeType.REALIZES,
        link_method="git_log",
        confidence=0.9,
    )
    assert e.link_method == "git_log"


def test_ticket_ref_link_method():
    e = Edge(
        from_id="function:src/x.py:foo",
        to_id="ticket:github:owner/repo/1",
        kind=EdgeType.REALIZES,
        link_method="ticket_ref",
        confidence=0.85,
    )
    assert e.link_method == "ticket_ref"


def test_link_reason_without_method_raises():
    with pytest.raises(ValidationError):
        Edge(
            from_id="function:src/x.py:foo",
            to_id="ticket:github:owner/repo/1",
            kind=EdgeType.REALIZES,
            link_reason="some reason",  # no link_method
            confidence=0.9,
        )


def test_calls_edge_cannot_have_link_method():
    with pytest.raises(ValidationError):
        Edge(
            from_id="function:src/a.py:foo",
            to_id="function:src/b.py:bar",
            kind=EdgeType.CALLS,
            link_method="git_log",  # not allowed for non-loom edges
        )


def test_edge_type_adapter_handles_new_types():
    assert EdgeTypeAdapter.is_valid_storage_name("REALIZES")
    assert EdgeTypeAdapter.is_valid_storage_name("CLOSES")
    assert EdgeTypeAdapter.is_valid_storage_name("VERIFIED_BY")
    assert EdgeTypeAdapter.is_valid_storage_name("DEPENDS_ON")
    assert EdgeTypeAdapter.to_storage(EdgeType.REALIZES) == "REALIZES"
