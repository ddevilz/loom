from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import logging

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.linker.prompts import drift_detection_prompt
from loom.llm.client import LLMClient as DriftLLM

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ViolationReport:
    code_id: str
    doc_id: str
    confidence: float
    reason: str | None
    edge: Edge


@dataclass(frozen=True)
class AstDriftReport:
    node_id: str
    changed: bool
    reasons: list[str]


_SIDE_EFFECT_KEYS = frozenset(
    {
        "is_async",
        "lambda_count",
        "method_ref_count",
    }
)


def detect_ast_drift(old_node: Node, new_node: Node) -> AstDriftReport:
    reasons: list[str] = []

    old_signature = old_node.metadata.get("signature")
    new_signature = new_node.metadata.get("signature")
    if (
        isinstance(old_signature, str)
        and isinstance(new_signature, str)
        and old_signature != new_signature
    ):
        reasons.append(f"signature_changed: {old_signature} -> {new_signature}")

    old_return_type = old_node.metadata.get("return_type") or None
    new_return_type = new_node.metadata.get("return_type") or None
    if old_return_type != new_return_type:
        reasons.append(f"return_type_changed: {old_return_type} -> {new_return_type}")

    old_params = old_node.metadata.get("params")
    new_params = new_node.metadata.get("params")
    if isinstance(old_params, list) and isinstance(new_params, list):
        removed = [param for param in old_params if param not in new_params]
        added = [param for param in new_params if param not in old_params]
        if removed:
            reasons.append(f"removed_parameters: {removed}")
        if added:
            reasons.append(f"added_parameters: {added}")

    for key in sorted(_SIDE_EFFECT_KEYS):
        old_value = old_node.metadata.get(key)
        new_value = new_node.metadata.get(key)
        if old_value == new_value:
            continue
        if old_value is None and new_value is not None:
            reasons.append(f"added_side_effect_indicator: {key}={new_value}")
        elif old_value is not None and new_value is None:
            reasons.append(f"removed_side_effect_indicator: {key}={old_value}")
        else:
            reasons.append(
                f"changed_side_effect_indicator: {key}: {old_value} -> {new_value}"
            )

    return AstDriftReport(node_id=new_node.id, changed=bool(reasons), reasons=reasons)


async def detect_violations(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    implements_edges: list[Edge],
    *,
    llm: DriftLLM,
    threshold: float = 0.6,
    model: str | None = None,
    max_concurrent_llm_calls: int = 10,
) -> list[ViolationReport]:
    """Check whether code nodes violate linked doc requirements via LLM.

    Returns `ViolationReport` objects for LOOM_IMPLEMENTS pairs whose violation
    confidence meets `threshold`. The caller is responsible for persisting the
    resulting edges, e.g. `await graph.bulk_create_edges([r.edge for r in reports])`.
    """
    code_by_id = {n.id: n for n in code_nodes}
    doc_by_id = {n.id: n for n in doc_nodes}

    # Filter valid edges upfront
    valid_edges: list[tuple[Edge, Node, Node]] = []
    for edge in implements_edges:
        if edge.kind != EdgeType.LOOM_IMPLEMENTS:
            continue
        code = code_by_id.get(edge.from_id)
        doc = doc_by_id.get(edge.to_id)
        if code is None or doc is None or not code.summary:
            continue
        valid_edges.append((edge, code, doc))

    if not valid_edges:
        return []

    # Process LLM calls concurrently with semaphore
    semaphore = asyncio.Semaphore(max_concurrent_llm_calls)

    async def _check_one(edge: Edge, code: Node, doc: Node) -> ViolationReport | None:
        async with semaphore:
            prompt = drift_detection_prompt(
                code_summary=code.summary, doc_text=doc.summary or doc.name
            )
            raw = await llm.complete(prompt=prompt, model=model)
            try:
                data: dict[str, Any] = json.loads(raw)
            except Exception as exc:
                logger.debug("LLM returned non-JSON for drift check (%s): %r", exc, raw[:200])
                return None
            if not isinstance(data, dict):
                return None

            violates = data.get("violates")
            confidence = data.get("confidence")
            reason = data.get("reason")
            if violates is not True or not isinstance(confidence, (int, float)):
                return None
            if float(confidence) < threshold:
                return None

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
            return ViolationReport(
                code_id=code.id,
                doc_id=doc.id,
                confidence=float(confidence),
                reason=str(reason) if reason is not None else None,
                edge=violation_edge,
            )

    results = await asyncio.gather(
        *[_check_one(edge, code, doc) for edge, code, doc in valid_edges]
    )
    return [r for r in results if r is not None]
