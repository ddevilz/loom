from __future__ import annotations

from typer.testing import CliRunner

import loom.cli


runner = CliRunner()


def test_cli_trace_unimplemented(monkeypatch) -> None:
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            pass

    async def fake_unimplemented(graph):
        from loom.core import Node, NodeKind, NodeSource

        return [Node(id="doc:jira:PROJ-1", kind=NodeKind.SECTION, source=NodeSource.DOC, name="PROJ-1", path="jira://PROJ/PROJ-1", metadata={})]

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.query.traceability.unimplemented_tickets", fake_unimplemented)

    result = runner.invoke(loom.cli.app, ["trace", "unimplemented"])
    assert result.exit_code == 0
    assert "PROJ-1" in result.stdout


def test_cli_trace_impact(monkeypatch) -> None:
    class FakeGraph:
        def __init__(self, graph_name: str = "loom", *, gateway=None) -> None:
            pass

    async def fake_impact(ticket_id, graph):
        from loom.core import Node, NodeKind, NodeSource

        return [Node(id="function:x:f", kind=NodeKind.FUNCTION, source=NodeSource.CODE, name="f", path="x", metadata={})]

    monkeypatch.setattr("loom.core.LoomGraph", FakeGraph)
    monkeypatch.setattr("loom.query.traceability.impact_of_ticket", fake_impact)

    result = runner.invoke(loom.cli.app, ["trace", "impact", "PROJ-1"])
    assert result.exit_code == 0
    assert "f" in result.stdout
