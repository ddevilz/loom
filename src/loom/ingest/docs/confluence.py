from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from loom.core import Node, NodeKind, NodeSource


@dataclass(frozen=True)
class ConfluenceConfig:
    base_url: str
    email: str
    api_token: str
    space_key: str
    cql: str | None = None
    
    def __post_init__(self) -> None:
        """Validate configuration to prevent security issues."""
        if not self.base_url:
            raise ValueError("Confluence base_url cannot be empty")
        if not self.email:
            raise ValueError("Confluence email cannot be empty")
        if not self.api_token:
            raise ValueError("Confluence api_token cannot be empty")
        if not self.space_key:
            raise ValueError("Confluence space_key cannot be empty")
        
        # Validate URL to prevent SSRF attacks
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Confluence base_url must use http or https scheme, got: {parsed.scheme}")
        if not parsed.netloc:
            raise ValueError("Confluence base_url must have a valid domain")
        if parsed.scheme == "http":
            import warnings
            warnings.warn(
                f"Confluence base_url uses insecure http:// scheme: {self.base_url}. "
                "Consider using https:// for security.",
                UserWarning,
                stacklevel=2
            )


def _build_cql(config: ConfluenceConfig) -> str:
    return config.cql or f'space = "{config.space_key}"'


def _auth_header(config: ConfluenceConfig) -> str:
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _fetch_pages(config: ConfluenceConfig) -> list[dict[str, Any]]:
    cql = quote(_build_cql(config))
    url = (
        f"{config.base_url.rstrip('/')}/wiki/rest/api/content/search"
        f"?cql={cql}&limit=100&expand=body.storage,version,space"
    )
    req = Request(
        url,
        headers={
            "Authorization": _auth_header(config),
            "Accept": "application/json",
        },
        method="GET",
    )
    # URL validation performed in ConfluenceConfig.__post_init__
    with urlopen(req, timeout=30) as resp:  # nosec B310
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
