from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


def test_serve_has_no_misleading_host_port_flags() -> None:
    """serve command must not expose --host/--port CLI flags unless they're wired to mcp.run()."""
    import inspect

    from loom.cli import serve

    src = inspect.getsource(serve)
    # Check for actual typer option flags (not just any mention of host/port in strings)
    has_host_flag = '"--host"' in src or "'--host'" in src
    has_port_flag = '"--port"' in src or "'--port'" in src
    if has_host_flag or has_port_flag:
        # If CLI flags exist, they must be forwarded to mcp.run()
        assert "host=host" in src or "port=port" in src, (
            "--host/--port flags exist in serve but are not passed to mcp.run()"
        )


def test_check_drift_response_has_no_semantic_violations_key() -> None:
    """check_drift must not return a vestigial 'semantic_violations' key."""
    spec = importlib.util.find_spec("loom.mcp.server")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin).read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "check_drift":
            func_source = ast.unparse(node)
            assert "semantic_violations" not in func_source, (
                "check_drift still contains vestigial 'semantic_violations' key — remove it"
            )
            return

    # If check_drift is not found as a top-level def (it may be nested), fall back to text search
    # Extract just the check_drift function region from source
    start = source.find("async def check_drift")
    if start != -1:
        end = source.find("\n    @mcp.tool()", start + 1)
        snippet = source[start:end] if end != -1 else source[start : start + 500]
        assert "semantic_violations" not in snippet, (
            "check_drift still contains vestigial 'semantic_violations' key — remove it"
        )
