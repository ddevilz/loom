from __future__ import annotations

from typer.testing import CliRunner

import loom.cli


runner = CliRunner()


def test_cli_calls_dump(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

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

    r = runner.invoke(loom.cli.app, ["calls", "--direction", "dump", "--graph-name", "g", "--limit", "1"])
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
                return [{"kind": "function", "name": "render", "path": "x", "confidence": 1.0}]
            return []

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)

    r = runner.invoke(
        loom.cli.app,
        ["calls", "--graph-name", "g", "--target", "App", "--direction", "callees", "--limit", "5"],
    )
    assert r.exit_code == 0
    assert seen["resolved"]
    assert seen["callees"]


def test_cli_calls_prints_lexical_context(monkeypatch):
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            self.graph_name = graph_name

        async def query(self, cypher: str, params=None):
            if "MATCH (a)-[:CONTAINS]->(b {id: $id})" in cypher:
                return [{"kind": "function", "name": "build_server", "path": "x", "relation": "parent"}]
            if "MATCH (a {id: $id})-[:CONTAINS]->(b)" in cypher:
                return [{"kind": "function", "name": "search_code", "path": "x", "relation": "child"}]
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
