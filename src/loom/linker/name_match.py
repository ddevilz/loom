from __future__ import annotations

import re

from loom.core import Edge, EdgeOrigin, EdgeType, Node


def _tokenize_name(name: str) -> set[str]:
    # snake_case
    parts = re.split(r"[_\W]+", name)
    tokens: list[str] = []
    for p in parts:
        if not p:
            continue
        # camelCase / PascalCase splitting
        camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", p)
        tokens.extend([t.lower() for t in camel.split() if t])
    return {t for t in tokens if t}


def _tokenize_text(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_]+", text)}


def link_by_name(
    code_nodes: list[Node],
    doc_nodes: list[Node],
    *,
    threshold: float = 0.6,
) -> list[Edge]:
    edges: list[Edge] = []

    for c in code_nodes:
        c_tokens = _tokenize_name(c.name)
        if not c_tokens:
            continue

        for d in doc_nodes:
            # Prefer summary (body text), fall back to name.
            d_text = d.summary or d.name
            d_tokens = _tokenize_text(d_text)
            if not d_tokens:
                continue

            overlap = c_tokens & d_tokens
            score = len(overlap) / max(len(c_tokens), 1)
            if score < threshold:
                continue

            edges.append(
                Edge(
                    from_id=c.id,
                    to_id=d.id,
                    kind=EdgeType.LOOM_IMPLEMENTS,
                    origin=EdgeOrigin.NAME_MATCH,
                    confidence=float(score),
                    link_method="name_match",
                    link_reason=f"token_overlap={sorted(overlap)}",
                    metadata={},
                )
            )

    return edges
