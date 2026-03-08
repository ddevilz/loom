from __future__ import annotations

import pytest

from loom.core import NodeKind
from loom.ingest.docs.notion import NotionConfig, fetch_notion_nodes


@pytest.mark.asyncio
async def test_fetch_notion_nodes_maps_pages(monkeypatch) -> None:
    monkeypatch.setattr(
        "loom.ingest.docs.notion._fetch_pages",
        lambda cfg: [
            {
                "id": "abc",
                "url": "https://notion.so/page",
                "archived": False,
                "last_edited_time": "2025-01-01",
                "properties": {
                    "Name": {
                        "type": "title",
                        "title": [{"plain_text": "Platform Plan"}],
                    }
                },
            }
        ],
    )
    nodes = await fetch_notion_nodes(NotionConfig(api_token="tok", database_id="db1"))
    assert len(nodes) == 1
    assert nodes[0].name == "Platform Plan"
    assert nodes[0].kind == NodeKind.DOCUMENT
    assert nodes[0].metadata["url"] == "https://notion.so/page"
