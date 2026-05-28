from __future__ import annotations

import pytest

from loom.graph.db import DB
from loom.graph.models import Node, NodeKind, NodeSource, QuestionType
from loom.intelligence.suggested_questions import suggest_questions
from loom.store import nodes as node_store


def _fn(path: str, name: str, community_id: str | None = None) -> Node:
    return Node(
        id=Node.make_code_id(NodeKind.FUNCTION, path, name),
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name=name,
        path=path,
        file_hash="h",
        community_id=community_id,
    )


@pytest.fixture
def db() -> DB:
    return DB(path=":memory:")


@pytest.mark.asyncio
async def test_suggest_questions_type_field_is_uppercase(db: DB) -> None:
    """type field must use QuestionType ALL-CAPS enum values."""
    # Create a dead-code function (no callers)
    node = _fn("a.py", "orphan")
    await node_store.bulk_upsert_nodes(db, [node])

    questions = await suggest_questions(db, limit=5)
    for q in questions:
        assert q["type"] == q["type"].upper(), (
            f"type '{q['type']}' is not uppercase — must use QuestionType enum"
        )
    # Specifically check dead_code question was emitted and has correct type
    types = [q["type"] for q in questions]
    assert QuestionType.DEAD_CODE in types
