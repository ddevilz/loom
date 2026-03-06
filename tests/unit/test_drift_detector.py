from __future__ import annotations

import pytest

from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.drift.detector import detect_violations


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def complete(self, *, prompt: str, model: str | None = None) -> str:
        return self.payload


@pytest.mark.asyncio
async def test_detect_violations_emits_loom_violates_report() -> None:
    code = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="stores passwords in plaintext",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s1",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Password policy",
        path="spec.md",
        summary="Passwords must be hashed before storage.",
        metadata={},
    )
    edge = Edge(from_id=code.id, to_id=doc.id, kind=EdgeType.LOOM_IMPLEMENTS, metadata={})

    llm = _FakeLLM('{"violates": true, "confidence": 0.9, "reason": "plaintext contradicts hashing requirement"}')
    reports = await detect_violations([code], [doc], [edge], llm=llm)

    assert reports
    assert reports[0].edge.kind == EdgeType.LOOM_VIOLATES
