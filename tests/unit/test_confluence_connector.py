from __future__ import annotations

import pytest

from loom.core import NodeKind
from loom.ingest.docs.confluence import ConfluenceConfig, fetch_confluence_nodes


@pytest.mark.asyncio
async def test_fetch_confluence_nodes_maps_pages(monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.ingest.docs.confluence._fetch_pages",
        lambda cfg: [
            {
                "id": "123",
                "title": "Auth Spec",
                "body": {"storage": {"value": "Authentication docs"}},
                "space": {"key": "ENG"},
                "version": {"number": 2},
            }
        ],
    )
    nodes = await fetch_confluence_nodes(
        ConfluenceConfig(base_url="https://example.atlassian.net", email="a@b.com", api_token="tok", space_key="ENG")
    )
    assert len(nodes) == 1
    assert nodes[0].name == "Auth Spec"
    assert nodes[0].kind == NodeKind.DOCUMENT
    assert nodes[0].metadata["space"] == "ENG"
