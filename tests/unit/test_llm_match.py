from __future__ import annotations

import pytest

from loom.core import Node, NodeKind, NodeSource
from loom.linker.llm_match import link_by_llm


class _FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls = 0

    async def complete(self, *, prompt: str, model: str | None = None) -> str:
        self.calls += 1
        return self.payload


@pytest.mark.asyncio
async def test_link_by_llm_emits_edge_when_implements_true_and_over_threshold() -> None:
    code = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="validates input",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Validation",
        path="spec.md",
        summary="Validate input.",
        metadata={},
    )

    llm = _FakeLLM('{"implements": true, "confidence": 0.9, "reason": "matches"}')
    edges = await link_by_llm([code], [doc], llm=llm, threshold=0.6)
    assert edges
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_link_by_llm_filters_low_confidence() -> None:
    code = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        summary="validates input",
        metadata={},
    )
    doc = Node(
        id="doc:spec.md:s",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name="Validation",
        path="spec.md",
        summary="Validate input.",
        metadata={},
    )

    llm = _FakeLLM('{"implements": true, "confidence": 0.1, "reason": "weak"}')
    edges = await link_by_llm([code], [doc], llm=llm, threshold=0.6)
    assert edges == []
