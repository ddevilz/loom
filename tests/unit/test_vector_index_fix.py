from __future__ import annotations

import pytest

from loom.search.searcher import search


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


class _VectorIndexWorkingGraph:
    """Mock graph where vector index query succeeds."""
    
    def __init__(self):
        self.vector_query_attempted = False
        self.fallback_query_attempted = False
    
    async def query(self, cypher: str, params=None):
        if "db.idx.vector.queryNodes" in cypher:
            self.vector_query_attempted = True
            return [
                {
                    "id": "function:x:f",
                    "kind": "function",
                    "name": "f",
                    "summary": "test function",
                    "path": "x",
                    "metadata": {},
                    "score": 0.9,
                }
            ]
        elif "MATCH (n) WHERE n.summary IS NOT NULL AND n.embedding IS NOT NULL" in cypher:
            self.fallback_query_attempted = True
            return []
        return []
    
    async def neighbors(self, node_id: str, depth: int = 1, edge_types=None, kind=None):
        return []


class _VectorIndexFailingGraph:
    """Mock graph where vector index query fails, forcing fallback."""
    
    def __init__(self):
        self.vector_query_attempted = False
        self.fallback_query_attempted = False
    
    async def query(self, cypher: str, params=None):
        if "db.idx.vector.queryNodes" in cypher:
            self.vector_query_attempted = True
            raise Exception("Invalid arguments for procedure 'db.idx.vector.queryNodes'")
        elif "MATCH (n) WHERE n.summary IS NOT NULL AND n.embedding IS NOT NULL" in cypher:
            self.fallback_query_attempted = True
            return [
                {
                    "id": "function:x:f",
                    "kind": "function",
                    "name": "f",
                    "summary": "test function",
                    "path": "x",
                    "metadata": {},
                    "embedding": [1.0, 0.0],
                }
            ]
        return []
    
    async def neighbors(self, node_id: str, depth: int = 1, edge_types=None, kind=None):
        return []


@pytest.mark.asyncio
async def test_search_uses_vector_index_when_available() -> None:
    """Verify that search attempts vector index query and does NOT fall back when it succeeds."""
    graph = _VectorIndexWorkingGraph()
    
    results = await search("test query", graph, limit=5, embedder=_FakeEmbedder())
    
    assert graph.vector_query_attempted, "Vector index query should be attempted"
    assert not graph.fallback_query_attempted, "Fallback should NOT be used when vector index works"
    assert len(results) > 0
    assert results[0].matched_via == "vector", "Results should be marked as coming from vector index"


@pytest.mark.asyncio
async def test_search_falls_back_when_vector_index_fails() -> None:
    """Verify that search falls back to brute-force when vector index fails."""
    graph = _VectorIndexFailingGraph()
    
    results = await search("test query", graph, limit=5, embedder=_FakeEmbedder())
    
    assert graph.vector_query_attempted, "Vector index query should be attempted first"
    assert graph.fallback_query_attempted, "Fallback should be used when vector index fails"
    assert len(results) > 0
    assert results[0].matched_via == "vector_fallback", "Results should be marked as coming from fallback"


def test_schema_init_creates_valid_vector_index_ddl() -> None:
    """Verify that the vector index DDL is syntactically correct with quoted similarity function."""
    from loom.core.falkor.schema import schema_init
    
    class _MockGateway:
        def __init__(self):
            self.graph_name = "test_graph"
            self.executed_queries = []
        
        def run(self, cypher: str, params=None, timeout=None):
            self.executed_queries.append(cypher)
    
    gw = _MockGateway()
    schema_init(gw, embedding_dim=768)
    
    vector_index_queries = [q for q in gw.executed_queries if "CREATE VECTOR INDEX" in q]
    assert len(vector_index_queries) == 1, "Should create exactly one vector index"
    
    vector_index_ddl = vector_index_queries[0]
    assert "similarityFunction: 'cosine'" in vector_index_ddl, \
        "Similarity function must be quoted (e.g., 'cosine' not cosine)"
    assert "dimension: 768" in vector_index_ddl, "Dimension should be set correctly"
    assert "FOR (n:Node) ON (n.embedding)" in vector_index_ddl, "Index should target Node.embedding with parenthesised attribute syntax"
