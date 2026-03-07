from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from loom.core import Node, NodeKind, NodeSource


@dataclass(frozen=True)
class NotionConfig:
    api_token: str
    database_id: str
    notion_version: str = "2022-06-28"


def _fetch_pages(config: NotionConfig) -> list[dict[str, Any]]:
    url = f"https://api.notion.com/v1/databases/{config.database_id}/query"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {config.api_token}",
            "Notion-Version": config.notion_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=b"{}",
        method="POST",
    )
    with urlopen(req) as resp:  # nosec
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("results") or [])


def _title_from_properties(properties: dict[str, Any]) -> str:
    for value in properties.values():
        if value.get("type") == "title":
            title_items = value.get("title") or []
            return "".join(str(item.get("plain_text") or "") for item in title_items).strip()
    return "Untitled"


def _normalize_page(page: dict[str, Any], config: NotionConfig) -> Node:
    page_id = str(page.get("id"))
    properties = page.get("properties") or {}
    title = _title_from_properties(properties)
    url = str(page.get("url") or "")
    summary = title
    return Node(
        id=f"doc:notion:{page_id}",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=title,
        summary=summary,
        path=f"notion://{config.database_id}/{page_id}",
        metadata={
            "url": url,
            "archived": page.get("archived", False),
            "last_edited_time": page.get("last_edited_time"),
        },
    )


async def fetch_notion_nodes(config: NotionConfig) -> list[Node]:
    pages = await asyncio.to_thread(_fetch_pages, config)
    return [_normalize_page(page, config) for page in pages]
