from __future__ import annotations

import importlib
import sys


def _check(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def main() -> int:
    # module names (not necessarily distribution names)
    modules = [
        ("falkordb", "falkordb"),
        ("pydantic", "pydantic"),
        ("tree_sitter", "tree_sitter"),
        ("fastembed", "fastembed"),
        ("litellm", "litellm"),
        ("mcp", "mcp"),
        ("fastmcp", "fastmcp"),
        ("typer", "typer"),
        ("rich", "rich"),
        ("watchfiles", "watchfiles"),
        ("igraph", "igraph"),
        ("leidenalg", "leidenalg"),
        ("gitpython", "git"),
    ]

    if sys.platform != "win32":
        modules.append(("uvloop", "uvloop"))

    ok_all = True
    for display, mod in modules:
        ok = _check(mod)
        print(f"{display}: {'OK' if ok else 'FAIL'}")
        ok_all = ok_all and ok

    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
