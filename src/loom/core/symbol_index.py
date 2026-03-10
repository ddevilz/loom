from __future__ import annotations

from collections import defaultdict

from .node_model import Node, NodeKind


class FileSymbolIndex:
    """Pre-built per-file interval index for containment lookups.

    Stores (start_line, end_line, span, node_id) tuples sorted by start_line.
    Lookups scan all entries for a file to find the narrowest containing span
    (typically <200 symbols per file).

    This is much faster than querying all symbols in the graph and checking
    line ranges for each one.

    Examples:
        >>> index = FileSymbolIndex.build(graph, [NodeKind.FUNCTION, NodeKind.METHOD])
        >>> symbol_id = index.find_containing_symbol(42, "auth.py")
        >>> # Returns the ID of the narrowest symbol containing line 42
    """

    __slots__ = ("_entries",)

    def __init__(
        self,
        entries: dict[str, list[tuple[int, int, int, str]]],
    ) -> None:
        """Initialize with pre-built entries.

        Args:
            entries: Mapping from file_path to sorted list of
                    (start_line, end_line, span, node_id) tuples
        """
        self._entries = entries

    def get_entries(self, file_path: str) -> list[tuple[int, int, int, str]] | None:
        """Get all symbol entries for a file.

        Args:
            file_path: The file path to look up

        Returns:
            List of (start_line, end_line, span, node_id) tuples,
            or None if the file has no indexed symbols
        """
        return self._entries.get(file_path)

    def find_containing_symbol(self, line: int, file_path: str) -> str | None:
        """Find the narrowest symbol containing a given line.

        Args:
            line: The line number to search for
            file_path: The file path containing the line

        Returns:
            The node ID of the narrowest containing symbol,
            or None if no symbol contains the line

        Examples:
            >>> index.find_containing_symbol(42, "auth.py")
            'function:auth.py:validate_user'
        """
        entries = self._entries.get(file_path)
        if not entries:
            return None

        best_id: str | None = None
        best_span = float("inf")

        for start, end, span, nid in entries:
            if start <= line <= end and span < best_span:
                best_span = span
                best_id = nid

        return best_id

    @classmethod
    def build(
        cls,
        nodes: list[Node],
        kinds: tuple[NodeKind, ...] | list[NodeKind],
    ) -> FileSymbolIndex:
        """Build a file symbol index from a list of nodes.

        Args:
            nodes: List of nodes to index
            kinds: Node kinds to include in the index (e.g., FUNCTION, METHOD)

        Returns:
            A new FileSymbolIndex instance

        Examples:
            >>> nodes = []
            >>> index = FileSymbolIndex.build(
            ...     nodes,
            ...     [NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS]
            ... )
        """
        entries: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)

        kinds_set = set(kinds)
        for node in nodes:
            if node.kind not in kinds_set:
                continue
            if not node.path or node.start_line is None or node.start_line <= 0:
                continue

            end_line = node.end_line or node.start_line
            span = end_line - node.start_line
            entries[node.path].append((node.start_line, end_line, span, node.id))

        # Sort each file's entries by start_line for efficient lookup
        for file_entries in entries.values():
            file_entries.sort(key=lambda t: t[0])

        return cls(entries)


def build_name_index(
    nodes: list[Node],
    kinds: tuple[NodeKind, ...] | list[NodeKind],
) -> dict[str, list[str]]:
    """Build a name-to-node-IDs index for symbol resolution.

    This is used for resolving calls, imports, and type references by name.

    Args:
        nodes: List of nodes to index
        kinds: Node kinds to include in the index

    Returns:
        Mapping from symbol name to list of node IDs

    Examples:
        >>> name_index = build_name_index(nodes, [NodeKind.FUNCTION, NodeKind.METHOD])
        >>> candidate_ids = name_index.get("validate_user", [])
        >>> # Returns all function/method IDs named "validate_user"
    """
    index: dict[str, list[str]] = {}
    kinds_set = set(kinds)

    for node in nodes:
        if node.kind in kinds_set:
            index.setdefault(node.name, []).append(node.id)

    return index


def build_file_index(nodes: list[Node]) -> dict[str, str]:
    """Build a file-path-to-node-ID index for file nodes.

    This is used for import resolution.

    Args:
        nodes: List of nodes to index

    Returns:
        Mapping from file path to file node ID

    Examples:
        >>> file_index = build_file_index(nodes)
        >>> file_id = file_index.get("auth.py")
        >>> # Returns the node ID for the file node
    """
    index: dict[str, str] = {}

    for node in nodes:
        if node.kind == NodeKind.FILE:
            index[node.path] = node.id

    return index
