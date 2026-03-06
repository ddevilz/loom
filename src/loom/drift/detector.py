from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.linker.prompts import drift_detection_prompt


class DriftLLM(Protocol):
    async def complete(self, *, prompt: str, model: str | None = None) -> str: ...


@dataclass(frozen=True)
class ViolationReport:
    code_id: str
    doc_id: str
    confidence: float
    reason: str | None
    edge: Edge


async def detect_violations(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    implements_edges: list[Edge],
    *,
    llm: DriftLLM,
    threshold: float = 0.6,
    model: str | None = None,
) -> list[ViolationReport]:
    code_by_id = {n.id: n for n in code_nodes}
    doc_by_id = {n.id: n for n in doc_nodes}
    reports: list[ViolationReport] = []

    for edge in implements_edges:
        if edge.kind != EdgeType.LOOM_IMPLEMENTS:
            continue
        code = code_by_id.get(edge.from_id)
        doc = doc_by_id.get(edge.to_id)
        if code is None or doc is None or not code.summary:
            continue

        prompt = drift_detection_prompt(code_summary=code.summary, doc_text=doc.summary or doc.name)
        raw = await llm.complete(prompt=prompt, model=model)
        try:
            data: dict[str, Any] = json.loads(raw)
        except Exception:
            continue

        violates = data.get("violates")
        confidence = data.get("confidence")
        reason = data.get("reason")
        if violates is not True or not isinstance(confidence, (int, float)):
            continue
        if float(confidence) < threshold:
            continue

        violation_edge = Edge(
            from_id=code.id,
            to_id=doc.id,
            kind=EdgeType.LOOM_VIOLATES,
            origin=EdgeOrigin.LLM_MATCH,
            confidence=float(confidence),
            link_method="llm_match",
            link_reason=str(reason) if reason is not None else None,
            metadata={},
        )
        reports.append(
            ViolationReport(
                code_id=code.id,
                doc_id=doc.id,
                confidence=float(confidence),
                reason=str(reason) if reason is not None else None,
                edge=violation_edge,
            )
        )

    return reports
