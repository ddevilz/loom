from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loom.core import Edge, Node

try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover
    CrossEncoder = None  # type: ignore


class PairReranker(Protocol):
    def rerank_batch(self, pairs: list[tuple[Node, Node]]) -> list[float]: ...

    def rerank(self, code_node: Node, doc_node: Node) -> float: ...


@dataclass
class CrossEncoderReranker:
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __post_init__(self) -> None:
        if CrossEncoder is None:
            raise RuntimeError("sentence-transformers is not available")
        self._model = CrossEncoder(self.model_name)

    def rerank(self, code_node: Node, doc_node: Node) -> float:
        return self.rerank_batch([(code_node, doc_node)])[0]

    def rerank_batch(self, pairs: list[tuple[Node, Node]]) -> list[float]:
        if not pairs:
            return []
        texts = [
            (code_node.summary or code_node.name, doc_node.summary or doc_node.name)
            for code_node, doc_node in pairs
        ]
        scores = self._model.predict(texts)
        return [float(score) for score in scores]


def rerank_edges(
    edges: list[Edge],
    *,
    code_nodes: list[Node],
    doc_nodes: list[Node],
    reranker: PairReranker,
    threshold: float = 0.0,
) -> list[Edge]:
    code_by_id = {node.id: node for node in code_nodes}
    doc_by_id = {node.id: node for node in doc_nodes}

    scored_candidates: list[tuple[Edge, Node, Node]] = []
    for edge in edges:
        code = code_by_id.get(edge.from_id)
        doc = doc_by_id.get(edge.to_id)
        if code is None or doc is None:
            continue
        scored_candidates.append((edge, code, doc))

    if not scored_candidates:
        return []

    pairs = [(code, doc) for _, code, doc in scored_candidates]
    if hasattr(reranker, "rerank_batch"):
        scores = reranker.rerank_batch(pairs)
    else:
        scores = [reranker.rerank(code, doc) for code, doc in pairs]

    reranked: list[Edge] = []
    for (edge, _, _), score in zip(scored_candidates, scores, strict=True):
        if score < threshold:
            continue
        reranked.append(
            edge.model_copy(
                update={
                    "confidence": float(score),
                    "link_reason": f"cross_encoder={score:.3f}",
                }
            )
        )

    return sorted(reranked, key=lambda edge: edge.confidence, reverse=True)
