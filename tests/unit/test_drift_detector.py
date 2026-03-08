from __future__ import annotations

import pytest

from loom.core import Edge, EdgeType, Node, NodeKind, NodeSource
from loom.drift.detector import detect_ast_drift, detect_violations


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


@pytest.mark.asyncio
async def test_detect_violations_ignores_non_object_json_response() -> None:
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

    llm = _FakeLLM("[]")
    reports = await detect_violations([code], [doc], [edge], llm=llm)

    assert reports == []


def test_detect_ast_drift_reports_signature_return_param_and_side_effect_changes() -> None:
    old_node = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        metadata={
            "signature": "f(x, y) -> int",
            "return_type": "int",
            "params": ["x", "y"],
        },
    )
    new_node = Node(
        id="function:x:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="x",
        metadata={
            "signature": "f(x, z) -> str",
            "return_type": "str",
            "params": ["x", "z"],
            "is_async": True,
        },
    )

    report = detect_ast_drift(old_node, new_node)

    assert report.changed is True
    assert any("signature_changed" in reason for reason in report.reasons)
    assert any("return_type_changed" in reason for reason in report.reasons)
    assert any("removed_parameters" in reason for reason in report.reasons)
    assert any("added_parameters" in reason for reason in report.reasons)
    assert any("added_side_effect_indicator" in reason for reason in report.reasons)
