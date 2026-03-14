from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from loom.core import Edge, EdgeOrigin, EdgeType, Node
from loom.linker.prompts import llm_match_prompt
from loom.llm.client import LLMClient

_MIN_TOKEN_OVERLAP = 1
_MAX_DOC_CANDIDATES_PER_CODE = 10


def _tokenize_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text):
        camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word)
        tokens.update(t.lower() for t in camel.split() if t)
    return tokens


def _candidate_pairs(
    code_nodes: list[Node], doc_nodes: list[Node]
) -> list[tuple[Node, Node]]:
    doc_candidates: list[tuple[Node, set[str]]] = []
    for doc_node in doc_nodes:
        doc_text = doc_node.summary or doc_node.name
        if not doc_text:
            continue
        doc_tokens = _tokenize_text(doc_text)
        if not doc_tokens:
            continue
        doc_candidates.append((doc_node, doc_tokens))

    pairs: list[tuple[Node, Node]] = []
    for code_node in code_nodes:
        if not code_node.summary:
            continue
        code_tokens = _tokenize_text(f"{code_node.name} {code_node.summary}")
        if not code_tokens:
            continue

        ranked_docs = sorted(
            (
                (len(code_tokens & doc_tokens), doc_node)
                for doc_node, doc_tokens in doc_candidates
                if len(code_tokens & doc_tokens) >= _MIN_TOKEN_OVERLAP
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked_docs:
            continue
        for _, doc_node in ranked_docs[:_MAX_DOC_CANDIDATES_PER_CODE]:
            pairs.append((code_node, doc_node))
    return pairs


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
    pairs = _candidate_pairs(code_nodes, doc_nodes)

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
