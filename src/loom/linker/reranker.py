from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loom.core import Edge, Node

try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover
    CrossEncoder = None  # type: ignore


class PairReranker(Protocol):
    def rerank(self, code_node: Node, doc_node: Node) -> float: ...


@dataclass
class CrossEncoderReranker:
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __post_init__(self) -> None:
        if CrossEncoder is None:
            raise RuntimeError("sentence-transformers is not available")
        self._model = CrossEncoder(self.model_name)

    def rerank(self, code_node: Node, doc_node: Node) -> float:
        code_text = code_node.summary or code_node.name
        doc_text = doc_node.summary or doc_node.name
        score = self._model.predict([(code_text, doc_text)])[0]
        return float(score)


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

    reranked: list[Edge] = []
    for edge in edges:
        code = code_by_id.get(edge.from_id)
        doc = doc_by_id.get(edge.to_id)
        if code is None or doc is None:
            continue
        score = reranker.rerank(code, doc)
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
