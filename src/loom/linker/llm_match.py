from __future__ import annotations

import asyncio
import json
from typing import Any

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.linker.prompts import llm_match_prompt
from loom.llm.client import LLMClient


async def link_by_llm(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    *,
    llm: LLMClient,
    threshold: float = 0.6,
    model: str | None = None,
    max_concurrent_llm_calls: int = 10,
) -> list[Edge]:
    semaphore = asyncio.Semaphore(max_concurrent_llm_calls)
    pairs = [
        (c, d)
        for c in code_nodes
        if c.summary
        for d in doc_nodes
        if (d.summary or d.name)
    ]

    async def _check_one(code_node: Node, doc_node: Node) -> Edge | None:
        async with semaphore:
            doc_text = doc_node.summary or doc_node.name
            prompt = llm_match_prompt(code_summary=code_node.summary, doc_text=doc_text)
            raw = await llm.complete(prompt=prompt, model=model)

        data: dict[str, Any]
        try:
            data = json.loads(raw)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None

        impl = data.get("implements")
        conf = data.get("confidence")
        reason = data.get("reason")

        if impl is not True:
            return None
        if not isinstance(conf, (int, float)):
            return None
        if float(conf) < threshold:
            return None

        return Edge(
            from_id=code_node.id,
            to_id=doc_node.id,
            kind=EdgeType.LOOM_IMPLEMENTS,
            origin=EdgeOrigin.LLM_MATCH,
            confidence=float(conf),
            link_method="llm_match",
            link_reason=str(reason) if reason is not None else None,
            metadata={},
        )

    results = await asyncio.gather(
        *[_check_one(code_node, doc_node) for code_node, doc_node in pairs]
    )
    return [edge for edge in results if edge is not None]
