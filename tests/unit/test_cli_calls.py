from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_callers_prints_results(monkeypatch, tmp_path: Path) -> None:
    from loom.core import Node, NodeKind, NodeSource

<<<<<<< HEAD
    caller_node = Node(
        id="function:src/a.py:caller",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="caller",
        path="src/a.py",
        language="python",
        metadata={},
=======
        async def query(self, cypher: str, params=None):
            if "MATCH (a)-[r:CALLS]->(b)" in cypher:
                return [
                    {
                        "from_name": "App",
                        "from_path": "src/App.tsx",
                        "to_name": "render",
                        "to_path": "src/main.tsx",
                        "confidence": 1.0,
                    }
                ]
            return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(
        loom.cli.app,
        ["calls", "--direction", "dump", "--graph-name", "g", "--limit", "1"],
    )
    assert r.exit_code == 0
    assert "App" in r.stdout


def test_cli_calls_callees_resolves_plain_name(monkeypatch):
    seen = {"resolved": False, "callees": False}

    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

        async def query(self, cypher: str, params=None):
            if "RETURN n.id AS id" in cypher:
                seen["resolved"] = True
                return [{"id": "function:x:App"}]
            if "MATCH (a {id: $id})-[r:CALLS]->(b)" in cypher:
                seen["callees"] = True
                return [
                    {
                        "kind": "function",
                        "name": "render",
                        "path": "x",
                        "confidence": 1.0,
                    }
                ]
            return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(
        loom.cli.app,
        [
            "calls",
            "--graph-name",
            "g",
            "--target",
            "App",
            "--direction",
            "callees",
            "--limit",
            "5",
        ],
>>>>>>> main
    )

    class _FakeGraphCallers:
        def __init__(self, db_path=None) -> None:
            pass

        async def neighbors(self, node_id, *, depth=1, edge_types=None, direction="both"):
            return [caller_node]

        async def get_nodes_by_name(self, name, limit=2):
            return [caller_node]

    monkeypatch.setattr("loom.cli.graph.LoomGraph", _FakeGraphCallers)

    r = runner.invoke(loom.cli.app, ["callers", "function:src/a.py:target"])
    assert r.exit_code == 0
<<<<<<< HEAD
    assert "caller" in r.stdout


def test_cli_callees_prints_results(monkeypatch, tmp_path: Path) -> None:
    from loom.core import Node, NodeKind, NodeSource

    callee_node = Node(
        id="function:src/b.py:callee",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="callee",
        path="src/b.py",
        language="python",
        metadata={},
    )

    class _FakeGraphCallees:
        def __init__(self, db_path=None) -> None:
            pass

        async def neighbors(self, node_id, *, depth=1, edge_types=None, direction="both"):
            return [callee_node]

        async def get_nodes_by_name(self, name, limit=2):
            return [callee_node]

    monkeypatch.setattr("loom.cli.graph.LoomGraph", _FakeGraphCallees)

    r = runner.invoke(loom.cli.app, ["callees", "function:src/a.py:caller"])
    assert r.exit_code == 0
    assert "callee" in r.stdout
=======
    assert seen["resolved"]
    assert seen["callees"]


def test_cli_calls_prints_lexical_context(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

        async def query(self, cypher: str, params=None):
            if "MATCH (a)-[:CONTAINS]->(b {id: $id})" in cypher:
                return [
                    {
                        "kind": "function",
                        "name": "build_server",
                        "path": "x",
                        "relation": "parent",
                    }
                ]
            if "MATCH (a {id: $id})-[:CONTAINS]->(b)" in cypher:
                return [
                    {
                        "kind": "function",
                        "name": "search_code",
                        "path": "x",
                        "relation": "child",
                    }
                ]
            if "MATCH (a {id: $id})-[r:CALLS]->(b)" in cypher:
                return []
            if "MATCH (a)-[r:CALLS]->(b {id: $id})" in cypher:
                return []
            return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(
        loom.cli.app,
        [
            "calls",
            "--graph-name",
            "g",
            "--target",
            "function:F:/loom/src/loom/mcp/server.py:build_server.get_callers",
            "--direction",
            "both",
            "--limit",
            "5",
        ],
    )

    assert r.exit_code == 0
    assert "=== lexical parents ===" in r.stdout
    assert "build_server" in r.stdout
    assert "=== lexical children ===" in r.stdout
    assert "search_code" in r.stdout
>>>>>>> main
