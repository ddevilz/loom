from __future__ import annotations

import pytest

from loom.query.traceability import impact_of_ticket, sprint_code_coverage, tickets_for_function, unimplemented_tickets, untraced_functions, untraced_functions_limited


class _FakeGraph:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def query(self, cypher: str, params=None):
        self.calls.append((cypher, params))
        return self.rows


@pytest.mark.asyncio
async def test_unimplemented_tickets_returns_doc_nodes() -> None:
    graph = _FakeGraph([{"id": "doc:jira:PROJ-1", "name": "PROJ-1", "summary": "s", "path": "jira://PROJ/PROJ-1", "metadata": {}}])
    rows = await unimplemented_tickets(graph)
    assert rows[0].name == "PROJ-1"


@pytest.mark.asyncio
async def test_untraced_functions_returns_code_nodes() -> None:
    graph = _FakeGraph([{"id": "function:x:f", "kind": "function", "name": "f", "summary": "s", "path": "x", "metadata": {}}])
    rows = await untraced_functions(graph)
    assert rows[0].name == "f"


@pytest.mark.asyncio
async def test_impact_of_ticket_and_tickets_for_function() -> None:
    code_graph = _FakeGraph([{"id": "function:x:f", "kind": "function", "name": "f", "summary": "s", "path": "x", "metadata": {}}])
    doc_graph = _FakeGraph([{"id": "doc:jira:PROJ-1", "name": "PROJ-1", "summary": "s", "path": "jira://PROJ/PROJ-1", "metadata": {}}])
    impact = await impact_of_ticket("PROJ-1", code_graph)
    impact_by_id = await impact_of_ticket("doc:jira:PROJ-1", code_graph)
    tickets = await tickets_for_function("function:x:f", doc_graph)
    assert impact[0].name == "f"
    assert impact_by_id[0].name == "f"
    assert tickets[0].name == "PROJ-1"


@pytest.mark.asyncio
async def test_untraced_functions_limited_passes_limit_and_path_prefix() -> None:
    graph = _FakeGraph([{"id": "function:x:f", "kind": "function", "name": "f", "summary": "s", "path": "x", "metadata": {}}])
    rows = await untraced_functions_limited(graph, limit=25, path_prefix="src/")
    assert rows[0].name == "f"
    _, params = graph.calls[-1]
    assert params == {"limit": 25, "path_prefix": "src/"}


@pytest.mark.asyncio
async def test_sprint_code_coverage_returns_report() -> None:
    graph = _FakeGraph([{"ticket_count": 3, "linked_function_count": 5}])
    report = await sprint_code_coverage("Sprint 1", graph)
    assert report.ticket_count == 3
    assert report.linked_function_count == 5
