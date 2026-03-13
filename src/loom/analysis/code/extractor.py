from __future__ import annotations

from loom.core import Node, NodeKind, NodeSource


def extract_summary(node: Node) -> str:
    """
    Extract a structured text summary from a node using only static metadata.
    No LLM calls, no network requests.

    For code nodes: produces structured format with kind, name, params, returns, etc.
    For doc nodes: returns node.summary or node.name unchanged.
    For file nodes: returns simple file description.
    """
    # Doc nodes pass through unchanged
    if node.source == NodeSource.DOC:
        return node.summary or node.name

    # File nodes
    if node.kind == NodeKind.FILE:
        return f"file: {node.name}\npath: {node.path}"

    # Code nodes (function, method, class, etc.)
    lines: list[str] = []

    # Kind and name (always present)
    lines.append(f"{node.kind.value}: {node.name}")

    # Parameters
    params = node.metadata.get("params")
    if isinstance(params, list) and params:
        lines.append(f"params: {', '.join(str(p) for p in params)}")
    elif params is not None and not isinstance(params, list):
        lines.append("params: none")

    # Return type
    return_type = node.metadata.get("return_type")
    if return_type:
        lines.append(f"returns: {return_type}")
    elif return_type is not None:
        lines.append("returns: unknown")

    # Raises/exceptions
    raises = node.metadata.get("raises")
    if isinstance(raises, list) and raises:
        lines.append(f"raises: {', '.join(str(r) for r in raises)}")
    elif raises is not None and not isinstance(raises, list):
        lines.append("raises: none")

    # Calls (if available from metadata)
    calls = node.metadata.get("calls")
    if isinstance(calls, list) and calls:
        lines.append(f"calls: {', '.join(str(c) for c in calls)}")
    elif calls is not None and not isinstance(calls, list):
        lines.append("calls: none")

    # Module/path
    lines.append(f"module: {node.path}")

    # Docstring (first 200 chars if present)
    docstring = node.metadata.get("docstring")
    if isinstance(docstring, str) and docstring.strip():
        doc_text = docstring.strip()
        if len(doc_text) > 200:
            doc_text = doc_text[:200] + "..."
        lines.append(f"docstring: {doc_text}")

    return "\n".join(lines)


async def extract_summaries(nodes: list[Node]) -> list[Node]:
    """Assign static summaries to nodes that don't have one yet.
    No LLM calls — uses extract_summary() for static extraction.
    """
    return [
        n if n.summary else n.model_copy(update={"summary": extract_summary(n)})
        for n in nodes
    ]
