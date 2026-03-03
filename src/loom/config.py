from __future__ import annotations

DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".venv",
        "venv",
        ".env",
        ".tox",
        ".eggs",
        ".next",
        ".nuxt",
        "target",
    }
)
