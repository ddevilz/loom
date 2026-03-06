from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from loom.core import Node, NodeKind, NodeSource


@dataclass(frozen=True)
class ConfluenceConfig:
    base_url: str
    email: str
    api_token: str
    space_key: str
    cql: str | None = None


def _build_cql(config: ConfluenceConfig) -> str:
    return config.cql or f'space = "{config.space_key}"'


def _fetch_pages(config: ConfluenceConfig) -> list[dict[str, Any]]:
    cql = quote(_build_cql(config))
    url = (
        f"{config.base_url.rstrip('/')}/wiki/rest/api/content/search"
        f"?cql={cql}&limit=100&expand=body.storage,version,space"
    )
    req = Request(
        url,
        headers={
            "Authorization": f"Basic {config.email}:{config.api_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(req) as resp:  # nosec
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("results") or [])


def _normalize_page(page: dict[str, Any], config: ConfluenceConfig) -> Node:
    page_id = str(page.get("id"))
    title = str(page.get("title") or page_id)
    body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
    version = (page.get("version") or {}).get("number")
    return Node(
        id=f"doc:confluence:{page_id}",
        kind=NodeKind.SECTION,
        source=NodeSource.DOC,
        name=title,
        summary=f"{title}. {str(body)[:500]}".strip(),
        path=f"confluence://{config.space_key}/{page_id}",
        metadata={
            "space": ((page.get("space") or {}).get("key")) or config.space_key,
            "version": version,
            "url": f"{config.base_url.rstrip('/')}/wiki/pages/viewpage.action?pageId={page_id}",
        },
    )


async def fetch_confluence_nodes(config: ConfluenceConfig) -> list[Node]:
    pages = await asyncio.to_thread(_fetch_pages, config)
    return [_normalize_page(page, config) for page in pages]
