from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import PurePath

from loom.core import Node, NodeSource
from loom.core.edge import Edge, EdgeOrigin, EdgeType
from loom.embed.embedder import cosine_similarity, embed_nodes
from loom.ingest.git_miner import MiningResult

logger = logging.getLogger(__name__)

_DEFAULT_EMBED_THRESHOLD = 0.72
_DEFAULT_GIT_CONFIDENCE = 0.90


def _is_test_node(node: Node) -> bool:
    """Return True if a code node appears to be a test function/method.

    Checks both the path and the node name for test indicators.

    Args:
        node: A code Node to inspect.

    Returns:
        True if the node looks like a test, False otherwise.
    """
    path = node.path or ""
    name = node.name or ""
    path_obj = PurePath(path.replace("\\", "/")) if path else None
    path_parts = tuple(part.lower() for part in path_obj.parts) if path_obj else ()
    file_name = path_obj.name.lower() if path_obj else ""

    path_is_test = (
        "tests" in path_parts
        or file_name.startswith("test_")
        or file_name.endswith("_test.py")
        or file_name.endswith("_test.ts")
        or file_name.endswith("_test.tsx")
        or file_name.endswith("_test.js")
        or file_name.endswith("_test.jsx")
    )
    name_is_test = name.startswith("test_") or name.startswith("Test")

    return path_is_test or name_is_test


async def link_tickets_by_embedding(
    ticket_nodes: list[Node],
    code_nodes: list[Node],
    *,
    threshold: float = _DEFAULT_EMBED_THRESHOLD,
) -> list[Edge]:
    """Link ticket nodes to code nodes via embedding similarity.

    Embeds both lists and creates REALIZES or VERIFIED_BY edges for pairs
    whose cosine similarity meets the threshold.

    Args:
        ticket_nodes: Nodes with NodeSource.TICKET.
        code_nodes: Nodes with NodeSource.CODE.
        threshold: Minimum cosine similarity to create an edge.

    Returns:
        Deduplicated list of REALIZES and VERIFIED_BY edges.
    """
    ticket_nodes = await embed_nodes(ticket_nodes)
    code_nodes = await embed_nodes(code_nodes)

    edges: list[Edge] = []

    for ticket in ticket_nodes:
        if ticket.embedding is None:
            continue
        for code in code_nodes:
            if code.embedding is None:
                continue
            score = cosine_similarity(ticket.embedding, code.embedding)
            if score < threshold:
                continue

            if _is_test_node(code):
                # ticket → code: this test verifies the ticket
                edges.append(
                    Edge(
                        from_id=ticket.id,
                        to_id=code.id,
                        kind=EdgeType.VERIFIED_BY,
                        origin=EdgeOrigin.EMBED_MATCH,
                        confidence=float(score),
                        link_method="embed_match",
                        link_reason=f"cosine={score:.3f}",
                        metadata={},
                    )
                )
            else:
                # code → ticket: this function realizes the ticket
                edges.append(
                    Edge(
                        from_id=code.id,
                        to_id=ticket.id,
                        kind=EdgeType.REALIZES,
                        origin=EdgeOrigin.EMBED_MATCH,
                        confidence=float(score),
                        link_method="embed_match",
                        link_reason=f"cosine={score:.3f}",
                        metadata={},
                    )
                )

    deduped = TicketLinker._dedupe_edges(edges)
    logger.info(
        "ticket_linker embed: %d edges from %d tickets x %d code nodes",
        len(deduped),
        len(ticket_nodes),
        len(code_nodes),
    )
    return deduped


def link_tickets_by_git_log(
    ticket_nodes: list[Node],
    code_nodes: list[Node],
    mining_result: MiningResult,
    *,
    confidence: float = _DEFAULT_GIT_CONFIDENCE,
) -> list[Edge]:
    """Link ticket nodes to code nodes using git log mining data.

    Creates high-confidence REALIZES or VERIFIED_BY edges based on which
    functions were modified in commits that reference each ticket.

    Args:
        ticket_nodes: Nodes with NodeSource.TICKET.
        code_nodes: Nodes with NodeSource.CODE.
        mining_result: Result from git_miner.mine_repo().

    Returns:
        Deduplicated list of REALIZES and VERIFIED_BY edges.
    """
    # Build ticket lookup: external_id and name → Node
    ticket_by_ref: dict[str, Node] = {}
    for ticket in ticket_nodes:
        if ticket.external_id:
            ticket_by_ref[ticket.external_id] = ticket
        if ticket.name:
            ticket_by_ref[ticket.name] = ticket

    # Build code lookup: file path → list of code nodes in that file
    code_by_path: dict[str, list[Node]] = {}
    for code in code_nodes:
        if code.path:
            code_by_path.setdefault(code.path, []).append(code)

    edges: list[Edge] = []

    for file_path, ticket_refs in mining_result.file_to_tickets.items():
        file_code_nodes = code_by_path.get(file_path, [])
        if not file_code_nodes:
            continue

        # Count commits that reference any ticket ref touching this file
        commits_for_file = [
            cr for cr in mining_result.commit_refs if file_path in cr.changed_files
        ]

        for ticket_ref in ticket_refs:
            ticket_node = ticket_by_ref.get(ticket_ref)
            if ticket_node is None:
                continue

            for code_node in file_code_nodes:
                link_reason = (
                    f"git log: {len(commits_for_file)} commits reference {ticket_ref}"
                )
                if _is_test_node(code_node):
                    # ticket → code: test verifies the ticket
                    edges.append(
                        Edge(
                            from_id=ticket_node.id,
                            to_id=code_node.id,
                            kind=EdgeType.VERIFIED_BY,
                            origin=EdgeOrigin.COMPUTED,
                            confidence=confidence,
                            link_method="git_log",
                            link_reason=link_reason,
                            metadata={},
                        )
                    )
                else:
                    # code → ticket: function realizes the ticket
                    edges.append(
                        Edge(
                            from_id=code_node.id,
                            to_id=ticket_node.id,
                            kind=EdgeType.REALIZES,
                            origin=EdgeOrigin.COMPUTED,
                            confidence=confidence,
                            link_method="git_log",
                            link_reason=link_reason,
                            metadata={},
                        )
                    )

    deduped = TicketLinker._dedupe_edges(edges)
    logger.info(
        "ticket_linker git_log: %d edges from %d file→ticket mappings",
        len(deduped),
        len(mining_result.file_to_tickets),
    )
    return deduped


@dataclass
class TicketLinker:
    """Links ticket nodes to code nodes using embedding similarity and git log mining."""

    embed_threshold: float = _DEFAULT_EMBED_THRESHOLD
    use_git_log: bool = True
    git_confidence: float = _DEFAULT_GIT_CONFIDENCE

    async def link(
        self,
        ticket_nodes: list[Node],
        code_nodes: list[Node],
        *,
        mining_result: MiningResult | None = None,
    ) -> list[Edge]:
        """Link ticket nodes to code nodes.

        Uses git log mining first (highest confidence), then embedding similarity
        for tickets not yet linked. Returns combined, deduplicated edge list.

        Args:
            ticket_nodes: Nodes with NodeKind.TICKET / NodeSource.TICKET
            code_nodes: Code nodes (functions, methods, classes)
            mining_result: Optional result from git_miner.mine_repo(). If provided
                and use_git_log=True, git-log edges are created first.

        Returns:
            List of REALIZES, CLOSES, and VERIFIED_BY edges.
        """
        filtered_tickets = [n for n in ticket_nodes if n.source == NodeSource.TICKET]
        filtered_code = [n for n in code_nodes if n.source == NodeSource.CODE]

        if not filtered_tickets or not filtered_code:
            return []

        all_edges: list[Edge] = []

        if self.use_git_log and mining_result is not None:
            git_edges = link_tickets_by_git_log(
                filtered_tickets,
                filtered_code,
                mining_result,
                confidence=self.git_confidence,
            )
            all_edges.extend(git_edges)

        embed_edges = await link_tickets_by_embedding(
            filtered_tickets,
            filtered_code,
            threshold=self.embed_threshold,
        )
        all_edges.extend(embed_edges)

        return self._dedupe_edges(all_edges)

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
