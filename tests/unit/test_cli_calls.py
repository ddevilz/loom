from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_callers_prints_results(monkeypatch, tmp_path: Path) -> None:
    from loom.core import Node, NodeKind, NodeSource

    caller_node = Node(
        id="function:src/a.py:caller",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="caller",
        path="src/a.py",
        language="python",
        metadata={},
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
