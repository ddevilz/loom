"""Comprehensive accuracy tests for CLI commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


class _MockGraphForAccuracyTest:
    """Mock graph with realistic data for accuracy testing."""

    def __init__(self):
        self.query_log = []

    async def query(self, cypher: str, params=None):
        self.query_log.append({"cypher": cypher, "params": params})

        # Handle vector index queries
        if "db.idx.vector.queryNodes" in cypher:
            return [
                {
                    "id": "function:src/auth.py:validate_password",
                    "kind": "function",
                    "name": "validate_password",
                    "summary": "Validates password strength and requirements",
                    "path": "src/auth.py",
                    "metadata": {},
                    "score": 0.92,
                },
                {
                    "id": "function:src/auth.py:authenticate_user",
                    "kind": "function",
                    "name": "authenticate_user",
                    "summary": "Authenticates user credentials",
                    "path": "src/auth.py",
                    "metadata": {},
                    "score": 0.88,
                },
                {
                    "id": "class:src/auth.py:AuthManager",
                    "kind": "class",
                    "name": "AuthManager",
                    "summary": "Manages authentication and authorization",
                    "path": "src/auth.py",
                    "metadata": {},
                    "score": 0.85,
                },
            ]

        # Handle CONTAINS queries (lexical parent/child)
        if "MATCH (a)-[:CONTAINS]->(b {id:" in cypher:
            node_id = params.get("id", "")
            if "authenticate_user" in node_id:
                return [
                    {
                        "kind": "class",
                        "name": "AuthManager",
                        "path": "src/auth.py",
                        "relation": "parent",
                    }
                ]
            return []

        if "MATCH (a {id: $id})-[:CONTAINS]->(b)" in cypher:
            node_id = params.get("id", "")
            if "AuthManager" in node_id:
                return [
                    {
                        "kind": "method",
                        "name": "authenticate_user",
                        "path": "src/auth.py",
                        "relation": "child",
                    },
                    {
                        "kind": "method",
                        "name": "validate_password",
                        "path": "src/auth.py",
                        "relation": "child",
                    },
                ]
            return []

        # Handle CALLS queries (callees)
        if "MATCH (a {id: $id})-[r:CALLS]->(b)" in cypher:
            return [
                {
                    "kind": "function",
                    "name": "hash_password",
                    "path": "src/crypto.py",
                    "confidence": 1.0,
                }
            ]

        # Handle CALLS queries (callers)
        if "MATCH (a)-[r:CALLS]->(b {id: $id})" in cypher:
            return [
                {
                    "kind": "function",
                    "name": "login_handler",
                    "path": "src/api.py",
                    "confidence": 0.95,
                }
            ]

        # Handle node resolution by name (exact match for calls command)
        if "RETURN n.id AS id" in cypher and "{name: $name}" in cypher:
            name = params.get("name", "")
            if name == "authenticate_user":
                return [{"id": "function:src/auth.py:authenticate_user"}]
            return []

        # Handle entrypoints query - name-based candidates
        if "toLower(n.name) IN" in cypher and "main" in cypher.lower():
            return [
                {
                    "id": "function:src/main.py:main",
                    "kind": "function",
                    "name": "main",
                    "path": "src/main.py",
                },
                {
                    "id": "function:src/api.py:app",
                    "kind": "function",
                    "name": "app",
                    "path": "src/api.py",
                },
            ]

        # Handle entrypoints query - call roots (no incoming CALLS)
        if "NOT ( ()-[:" in cypher and "]->(n) )" in cypher:
            return [
                {
                    "kind": "function",
                    "name": "main",
                    "path": "src/main.py",
                    "out_calls": 5,
                },
            ]

        return []

    async def neighbors(self, node_id: str, depth: int = 1, edge_types=None, kind=None):
        return []


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.5, 0.5] for _ in texts]


def test_query_command_uses_vector_index_not_fallback(monkeypatch) -> None:
    """Verify query command attempts vector index and returns results."""
    graph = _MockGraphForAccuracyTest()

    monkeypatch.setattr(
        "loom.core.LoomGraph", lambda graph_name="loom", gateway=None: graph
    )
    monkeypatch.setattr("loom.search.searcher.FastEmbedder", _FakeEmbedder)

    result = runner.invoke(
        loom.cli.app,
        [
            "query",
            "authentication password validation",
            "--graph-name",
            "test",
            "--limit",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert "validate_password" in result.stdout
    assert "authenticate_user" in result.stdout

    # Verify vector index was attempted
    vector_queries = [
        log for log in graph.query_log if "db.idx.vector.queryNodes" in log["cypher"]
    ]
    assert len(vector_queries) > 0, "Should attempt vector index query"


def test_calls_command_shows_lexical_and_runtime_context(monkeypatch) -> None:
    """Verify calls command shows both CONTAINS (lexical) and CALLS (runtime) edges."""
    graph = _MockGraphForAccuracyTest()

    monkeypatch.setattr(
        "loom.core.LoomGraph", lambda graph_name="loom", gateway=None: graph
    )

    result = runner.invoke(
        loom.cli.app,
        [
            "calls",
            "--target",
            "function:src/auth.py:authenticate_user",
            "--direction",
            "both",
            "--graph-name",
            "test",
        ],
    )

    assert result.exit_code == 0

    # Should show lexical parent
    assert "=== lexical parents ===" in result.stdout
    assert "AuthManager" in result.stdout

    # Should show runtime callees
    assert "=== callees ===" in result.stdout
    assert "hash_password" in result.stdout

    # Should show runtime callers
    assert "=== callers ===" in result.stdout
    assert "login_handler" in result.stdout


def test_calls_command_works_with_full_id(monkeypatch) -> None:
    """Verify calls command works with full node IDs."""
    graph = _MockGraphForAccuracyTest()

    monkeypatch.setattr(
        "loom.core.LoomGraph", lambda graph_name="loom", gateway=None: graph
    )

    result = runner.invoke(
        loom.cli.app,
        [
            "calls",
            "--target",
            "function:auth.py:authenticate_user",
            "--direction",
            "both",
            "--graph-name",
            "test",
        ],
    )

    assert result.exit_code == 0

    # Should show results for the full ID
    assert "hash_password" in result.stdout or "login_handler" in result.stdout


def test_entrypoints_command_finds_potential_roots(monkeypatch) -> None:
    """Verify entrypoints command finds functions with no incoming CALLS edges."""
    graph = _MockGraphForAccuracyTest()

    monkeypatch.setattr(
        "loom.core.LoomGraph", lambda graph_name="loom", gateway=None: graph
    )

    result = runner.invoke(
        loom.cli.app,
        ["entrypoints", "--graph-name", "test", "--limit", "10"],
    )

    assert result.exit_code == 0
    assert "main" in result.stdout
    assert "app" in result.stdout


@pytest.mark.asyncio
async def test_search_prioritizes_high_scoring_results() -> None:
    """Verify search returns results in descending score order."""
    from loom.search.searcher import search

    graph = _MockGraphForAccuracyTest()
    results = await search("authentication", graph, limit=5, embedder=_FakeEmbedder())

    assert len(results) > 0

    # Results should be sorted by score descending
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True), (
        "Results should be sorted by score descending"
    )

    # Highest scoring result should be first
    assert results[0].node.name == "validate_password"
    assert results[0].score == pytest.approx(0.92)
