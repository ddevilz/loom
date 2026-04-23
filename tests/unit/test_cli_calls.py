from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli
from loom.core.context import DB

runner = CliRunner()


def test_cli_callers_prints_results(monkeypatch, tmp_path: Path) -> None:
    from loom.core.node import Node, NodeKind, NodeSource

    caller_node = Node(
        id="function:src/a.py:caller",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="caller",
        path="src/a.py",
        language="python",
        metadata={},
    )

    async def fake_neighbors(db, node_id, *, depth=1, edge_types=None, direction="both"):
        return [caller_node]

    monkeypatch.setattr("loom.cli.graph.traversal.neighbors", fake_neighbors)

    r = runner.invoke(
        loom.cli.app,
        ["callers", "function:src/a.py:target"],
        obj={"db": DB(path=":memory:")},
    )
    assert r.exit_code == 0
    assert "caller" in r.stdout


def test_cli_callees_prints_results(monkeypatch, tmp_path: Path) -> None:
    from loom.core.node import Node, NodeKind, NodeSource

    callee_node = Node(
        id="function:src/b.py:callee",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="callee",
        path="src/b.py",
        language="python",
        metadata={},
    )

    async def fake_neighbors(db, node_id, *, depth=1, edge_types=None, direction="both"):
        return [callee_node]

    monkeypatch.setattr("loom.cli.graph.traversal.neighbors", fake_neighbors)

    r = runner.invoke(
        loom.cli.app,
        ["callees", "function:src/a.py:caller"],
        obj={"db": DB(path=":memory:")},
    )
    assert r.exit_code == 0
    assert "callee" in r.stdout
