"""AutoTagger — post-parse pass that applies decorator, import, and directory tags.

This module is pure computation: it takes already-parsed nodes plus file-level
metadata and returns a mapping of node_id -> [tags].  No database access occurs
here; the pipeline is responsible for persisting the result via
repo.tags.add_tags().
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.graph.models.node import Node

# ---------------------------------------------------------------------------
# Tag lookup tables
# ---------------------------------------------------------------------------

DECORATOR_TAGS: dict[str, str] = {
    "@app.route":       "api-endpoint",
    "@router.":         "api-endpoint",
    "@pytest.fixture":  "test-fixture",
    "@abstractmethod":  "interface",
    "@staticmethod":    "static",
    "@classmethod":     "class-method",
    "@property":        "property",
    "@contextmanager":  "context-manager",
    "@celery.task":     "async-task",
    "@Controller":      "api-endpoint",
    "@Injectable":      "service",
    "@Component":       "framework-component",
    "@RestController":  "api-endpoint",
    "@Service":         "service",
    "@Repository":      "repository",
    "@Test":            "test",
}

IMPORT_TAGS: dict[str, list[str]] = {
    "jwt":        ["auth", "jwt"],
    "oauth":      ["auth", "oauth"],
    "bcrypt":     ["auth", "crypto"],
    "passlib":    ["auth", "crypto"],
    "sqlalchemy": ["database", "orm"],
    "psycopg":    ["database"],
    "redis":      ["cache"],
    "celery":     ["async-task", "queue"],
    "flask":      ["web"],
    "fastapi":    ["web", "api"],
    "django":     ["web"],
    "express":    ["web"],
    "logging":    ["observability"],
    "structlog":  ["observability"],
}

DIR_TAGS: dict[str, str] = {
    "middleware": "middleware",
    "utils":      "utility",
    "helpers":    "utility",
    "migrations": "migration",
    "fixtures":   "test-data",
    "scripts":    "script",
    "proto":      "grpc",
    "graphql":    "graphql",
    "commands":   "cli",
    "workers":    "async-worker",
    "hooks":      "hook",
}

# Precompile the path-segment splitter (handles both / and \)
_PATH_SEP = re.compile(r"[/\\]")


class AutoTagger:
    """Pure-computation tagger: no constructor args, no DB access."""

    def tag_file(
        self,
        nodes: list[Node],
        imports: list[str],
        path: str,
    ) -> dict[str, list[str]]:
        """Apply decorator, import, and directory tags to a list of nodes.

        Returns mapping of node_id -> list of tags applied (for testing/debugging).
        Does NOT write to the database — caller does that via repo.tags.add_tags().
        """
        # Accumulator: node_id -> set of tags (deduplicates within a pass)
        result: dict[str, set[str]] = {node.id: set() for node in nodes}

        # ------------------------------------------------------------------ #
        # 1. Decorator tags — per-node
        # ------------------------------------------------------------------ #
        for node in nodes:
            decorators: list[str] = []
            if node.metadata:
                decorators = node.metadata.get("decorators", []) or []

            for decorator in decorators:
                for key, tag in DECORATOR_TAGS.items():
                    if decorator.startswith(key):
                        result[node.id].add(tag)
                        break  # first matching key wins for this decorator

        # ------------------------------------------------------------------ #
        # 2. Import tags — file-level (applied to all nodes)
        # ------------------------------------------------------------------ #
        import_tags: set[str] = set()
        for imp in imports:
            imp_lower = imp.lower()
            for key, tags in IMPORT_TAGS.items():
                if key in imp_lower:
                    import_tags.update(tags)

        for node in nodes:
            result[node.id].update(import_tags)

        # ------------------------------------------------------------------ #
        # 3. Directory tags — file-level (applied to all nodes)
        # ------------------------------------------------------------------ #
        segments = _PATH_SEP.split(path)
        dir_tags: set[str] = set()
        for seg in segments:
            seg_lower = seg.lower()
            if seg_lower in DIR_TAGS:
                dir_tags.add(DIR_TAGS[seg_lower])

        for node in nodes:
            result[node.id].update(dir_tags)

        # Convert sets -> sorted lists for deterministic output
        return {node_id: sorted(tags) for node_id, tags in result.items()}
