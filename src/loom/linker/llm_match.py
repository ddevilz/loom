from __future__ import annotations

import json
from typing import Any

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.llm.client import LLMClient
from loom.linker.prompts import llm_match_prompt


async def link_by_llm(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    *,
    llm: LLMClient,
    threshold: float = 0.6,
    model: str | None = None,
) -> list[Edge]:
    edges: list[Edge] = []

    for c in code_nodes:
        if not c.summary:
            continue
        for d in doc_nodes:
            doc_text = d.summary or d.name
            if not doc_text:
                continue

            prompt = llm_match_prompt(code_summary=c.summary, doc_text=doc_text)
            raw = await llm.complete(prompt=prompt, model=model)

            data: dict[str, Any]
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue

            impl = data.get("implements")
            conf = data.get("confidence")
            reason = data.get("reason")

            if impl is not True:
                continue
            if not isinstance(conf, (int, float)):
                continue
            if float(conf) < threshold:
                continue

            edges.append(
                Edge(
                    from_id=c.id,
                    to_id=d.id,
                    kind=EdgeType.LOOM_IMPLEMENTS,
                    origin=EdgeOrigin.LLM_MATCH,
                    confidence=float(conf),
                    link_method="llm_match",
                    link_reason=str(reason) if reason is not None else None,
                    metadata={},
                )
            )

    return edges
