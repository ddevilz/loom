from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from loom.core import Edge, EdgeOrigin, Node
from loom.linker.embed_match import link_by_embedding
from loom.linker.llm_match import link_by_llm
from loom.linker.name_match import link_by_name
from loom.linker.reranker import PairReranker, rerank_edges

logger = logging.getLogger(__name__)


class SummaryLLMClient(Protocol):
    async def summarize(
        self, *, prompt: str, max_tokens: int = 200, model: str | None = None
    ) -> str: ...


class _Graph(Protocol):
    async def bulk_create_edges(self, edges: list[Edge]) -> None: ...


@dataclass
class SemanticLinker:
    name_threshold: float = 0.6
    embedding_threshold: float = 0.75
    llm_threshold: float = 0.6
    llm_fallback: bool = False
    summary_llm: SummaryLLMClient | None = None
    match_llm: object | None = None
    reranker: PairReranker | None = None
    rerank_threshold: float = 0.0

    async def link(
        self,
        code_nodes: list[Node],
        doc_nodes: list[Node],
        graph: _Graph,
    ) -> list[Edge]:
        tier1 = link_by_name(code_nodes, doc_nodes, threshold=self.name_threshold)
        tier2 = await link_by_embedding(
            code_nodes,
            doc_nodes,
            threshold=self.embedding_threshold,
            graph=graph,
        )
        if self.reranker is not None and tier2:
            tier2 = rerank_edges(
                tier2,
                code_nodes=code_nodes,
                doc_nodes=doc_nodes,
                reranker=self.reranker,
                threshold=self.rerank_threshold,
            )
        all_edges = self._dedupe_edges([*tier1, *tier2])

        if self.llm_fallback:
            if self.match_llm is not None:
                tier3 = await link_by_llm(
                    code_nodes,
                    doc_nodes,
                    llm=self.match_llm,
                    threshold=self.llm_threshold,
                )
                all_edges = self._dedupe_edges([*all_edges, *tier3])
            else:
                logger.debug(
                    "LLM not configured — skipping LLM match tier. Set LOOM_LLM_MODEL to enable."
                )

        if all_edges:
            await graph.bulk_create_edges(all_edges)
        return all_edges

    @staticmethod
    def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
        best: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            key = (edge.from_id, edge.to_id, edge.kind.value)
            current = best.get(key)
            if current is None:
                best[key] = edge
                continue
            if current.origin == EdgeOrigin.HUMAN and edge.origin != EdgeOrigin.HUMAN:
                continue
            if edge.origin == EdgeOrigin.HUMAN and current.origin != EdgeOrigin.HUMAN:
                best[key] = edge
                continue
            if edge.confidence > current.confidence:
                best[key] = edge
        return list(best.values())
