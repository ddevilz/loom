from __future__ import annotations

import pytest
from pydantic import ValidationError

from loom.core.node import Node, NodeKind, NodeSource


def test_ticket_node_kind_enum():
    assert NodeKind.TICKET == "ticket"
    assert NodeKind.TICKET in list(NodeKind)


def test_ticket_node_source_enum():
    assert NodeSource.TICKET == "ticket"
    assert NodeSource.TICKET in list(NodeSource)


def test_make_ticket_id():
    tid = Node.make_ticket_id("github", "owner/repo", "42")
    assert tid == "ticket:github:owner/repo/42"

    tid2 = Node.make_ticket_id("jira", "PROJ", "PROJ-42")
    assert tid2 == "ticket:jira:PROJ/PROJ-42"


def test_ticket_node_creation():
    node = Node(
        id="ticket:github:owner/repo/42",
        kind=NodeKind.TICKET,
        source=NodeSource.TICKET,
        name="#42",
        path="github://owner/repo/42",
        status="open",
        priority="high",
        assignee="alice",
        url="https://github.com/owner/repo/issues/42",
        external_id="42",
    )
    assert node.is_ticket
    assert not node.is_code
    assert not node.is_doc
    assert node.status == "open"
    assert node.external_id == "42"


def test_ticket_node_id_must_start_with_ticket():
    with pytest.raises(ValidationError, match="ticket:"):
        Node(
            id="doc:github:owner/repo/42",  # wrong prefix for TICKET source
            kind=NodeKind.TICKET,
            source=NodeSource.TICKET,
            name="#42",
            path="github://owner/repo/42",
        )


def test_ticket_node_model_dump_excludes_computed():
    node = Node(
        id="ticket:github:owner/repo/1",
        kind=NodeKind.TICKET,
        source=NodeSource.TICKET,
        name="#1",
        path="github://owner/repo/1",
    )
    dumped = node.model_dump()
    assert "is_ticket" not in dumped
    assert "is_code" not in dumped
    assert "is_doc" not in dumped


def test_ticket_node_optional_fields_default_none():
    node = Node(
        id="ticket:github:owner/repo/1",
        kind=NodeKind.TICKET,
        source=NodeSource.TICKET,
        name="#1",
        path="github://owner/repo/1",
    )
    assert node.status is None
    assert node.priority is None
    assert node.assignee is None
    assert node.url is None
    assert node.external_id is None


def test_code_node_ticket_fields_remain_none():
    """Code nodes should not have ticket-specific fields set."""
    node = Node(
        id="function:src/auth.py:validate_user",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="validate_user",
        path="src/auth.py",
    )
    assert not node.is_ticket
    assert node.status is None
