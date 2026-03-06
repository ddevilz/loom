from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loom.analysis.code.summarizer import LLMClient as SummaryLLMClient
from loom.analysis.code.summarizer import summarize_nodes
from loom.core import Edge, Node
from loom.linker.embed_match import link_by_embedding
from loom.linker.llm_match import link_by_llm
from loom.linker.name_match import link_by_name


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

    async def link(
        self,
        code_nodes: list[Node],
        doc_nodes: list[Node],
        graph: _Graph,
    ) -> list[Edge]:
        summarized_code = await summarize_nodes(code_nodes, llm=self.summary_llm)

        tier1 = link_by_name(summarized_code, doc_nodes, threshold=self.name_threshold)
        matched_code_ids = {e.from_id for e in tier1}
        matched_doc_ids = {e.to_id for e in tier1}

        unmatched_code = [n for n in summarized_code if n.id not in matched_code_ids]
        unmatched_doc = [n for n in doc_nodes if n.id not in matched_doc_ids]

        tier2 = await link_by_embedding(unmatched_code, unmatched_doc, threshold=self.embedding_threshold)
        all_edges = self._dedupe_edges([*tier1, *tier2])

        if self.llm_fallback and self.match_llm is not None:
            matched_code_ids = {e.from_id for e in all_edges}
            matched_doc_ids = {e.to_id for e in all_edges}
            still_unmatched_code = [n for n in summarized_code if n.id not in matched_code_ids]
            still_unmatched_doc = [n for n in doc_nodes if n.id not in matched_doc_ids]
            tier3 = await link_by_llm(
                still_unmatched_code,
                still_unmatched_doc,
                llm=self.match_llm,
                threshold=self.llm_threshold,
            )
            all_edges = self._dedupe_edges([*all_edges, *tier3])

        if all_edges:
            await graph.bulk_create_edges(all_edges)
        return all_edges

    @staticmethod
    def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
        best: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            key = (edge.from_id, edge.to_id, edge.kind.value)
            current = best.get(key)
            if current is None or edge.confidence > current.confidence:
                best[key] = edge
        return list(best.values())
