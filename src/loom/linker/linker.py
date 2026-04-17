# src/loom/linker/linker.py
from __future__ import annotations

import logging
from dataclasses import dataclass

from loom.config import LOOM_LINKER_EMBED_THRESHOLD
from loom.core import Edge, EdgeOrigin, Node
from loom.core.types import BulkGraph
from loom.linker.embed_match import link_by_embedding

logger = logging.getLogger(__name__)


@dataclass
class SemanticLinker:
    """Links markdown doc nodes to code nodes by embedding similarity only.

    Does NOT link Jira tickets — use git_linker.link_commits_to_tickets() for that.
    """

    embedding_threshold: float = LOOM_LINKER_EMBED_THRESHOLD

    async def link(
        self,
        code_nodes: list[Node],
        doc_nodes: list[Node],
        graph: BulkGraph,
    ) -> list[Edge]:
        # embed_match → embed_nodes → asyncio.to_thread(embedder.embed, batch)
        # CPU-bound fastembed work is already offloaded to thread pool inside embed_nodes.
        edges = await link_by_embedding(
            code_nodes,
            doc_nodes,
            threshold=self.embedding_threshold,
            graph=graph,
        )
        deduped = self._dedupe_edges(edges)
        if deduped:
            await graph.bulk_create_edges(deduped)
        return deduped

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
