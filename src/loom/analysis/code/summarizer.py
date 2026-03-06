from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from loom.core import Node


_LOG = logging.getLogger(__name__)


class SummarizationStrategy(StrEnum):
    AUTO = "auto"
    DOCSTRING_ONLY = "docstring_only"
    SIGNATURE_ONLY = "signature_only"
    LOCAL = "local"
    CLOUD = "cloud"


class LLMClient(Protocol):
    async def summarize(self, *, prompt: str, max_tokens: int = 200, model: str | None = None) -> str: ...


@dataclass(frozen=True)
class SummarizationStats:
    docstring: int = 0
    signature: int = 0
    local: int = 0
    cloud: int = 0


_COMMENT_PREFIXES = ("#", "//")


def is_trivial_change(old_source: str, new_source: str) -> bool:
    def norm(s: str) -> str:
        out: list[str] = []
        for line in s.splitlines():
            t = line.strip()
            if not t:
                continue
            if t.startswith(_COMMENT_PREFIXES):
                continue
            # drop block comment single-line markers
            if t.startswith("/*") and t.endswith("*/"):
                continue
            out.append(re.sub(r"\s+", "", t))
        return "\n".join(out)

    return norm(old_source) == norm(new_source)


def _docstring_from_metadata(node: Node) -> str | None:
    doc = node.metadata.get("docstring")
    if isinstance(doc, str):
        doc = doc.strip()
        return doc or None
    return None


def _signature_from_metadata(node: Node) -> str | None:
    sig = node.metadata.get("signature")
    if isinstance(sig, str):
        sig = sig.strip()
        return sig or None

    params = node.metadata.get("params")
    ret = node.metadata.get("return_type")

    if isinstance(params, list) and all(isinstance(p, str) for p in params):
        ret_s = f" -> {ret}" if isinstance(ret, str) and ret else ""
        return f"{node.name}({', '.join(params)}){ret_s}"

    return None


async def summarize_nodes(
    nodes: list[Node],
    llm: LLMClient | None = None,
    strategy: SummarizationStrategy = SummarizationStrategy.AUTO,
    previous_nodes: list[Node] | None = None,
    *,
    local_model: str = "llama3.2",
    cloud_model: str = "gpt-4o-mini",
    cloud_threshold: float = 0.0,
    max_tokens_per_function: int = 200,
) -> list[Node]:
    stats = SummarizationStats()
    out: list[Node] = []

    prev_by_id: dict[str, Node] = {n.id: n for n in (previous_nodes or [])}

    for n in nodes:
        prev = prev_by_id.get(n.id)
        if prev is not None and prev.summary is not None:
            if prev.content_hash == n.content_hash:
                out.append(n.model_copy(update={"summary": prev.summary}))
                continue

            old_src = prev.metadata.get("source_text") if isinstance(prev.metadata, dict) else None
            new_src = n.metadata.get("source_text") if isinstance(n.metadata, dict) else None
            if isinstance(old_src, str) and isinstance(new_src, str):
                if is_trivial_change(old_src, new_src):
                    out.append(n.model_copy(update={"summary": prev.summary}))
                    continue

        if n.summary:
            out.append(n)
            continue

        doc = _docstring_from_metadata(n)
        sig = _signature_from_metadata(n)

        chosen: str | None = None
        used_llm = False

        if doc is not None:
            chosen = doc
            stats = SummarizationStats(
                docstring=stats.docstring + 1,
                signature=stats.signature,
                local=stats.local,
                cloud=stats.cloud,
            )
        elif strategy == SummarizationStrategy.DOCSTRING_ONLY:
            chosen = None
        elif sig is not None and strategy in {
            SummarizationStrategy.AUTO,
            SummarizationStrategy.SIGNATURE_ONLY,
        }:
            chosen = sig
            stats = SummarizationStats(
                docstring=stats.docstring,
                signature=stats.signature + 1,
                local=stats.local,
                cloud=stats.cloud,
            )
        else:
            if llm is None:
                chosen = f"{n.kind.value} {n.name} ({n.path})"
            else:
                prompt = f"Summarize what this code element does:\n\nName: {n.name}\nKind: {n.kind.value}\nPath: {n.path}\n"
                model = None
                if strategy == SummarizationStrategy.CLOUD or (
                    strategy == SummarizationStrategy.AUTO and cloud_threshold > 0.0
                ):
                    model = cloud_model
                    stats = SummarizationStats(
                        docstring=stats.docstring,
                        signature=stats.signature,
                        local=stats.local,
                        cloud=stats.cloud + 1,
                    )
                else:
                    model = local_model
                    stats = SummarizationStats(
                        docstring=stats.docstring,
                        signature=stats.signature,
                        local=stats.local + 1,
                        cloud=stats.cloud,
                    )

                chosen = await llm.summarize(
                    prompt=prompt,
                    max_tokens=max_tokens_per_function,
                    model=model,
                )
                used_llm = True

        if chosen is None:
            out.append(n)
            continue

        # Keep output deterministic-ish.
        chosen = chosen.strip()
        if used_llm and not chosen:
            chosen = f"{n.kind.value} {n.name} ({n.path})"

        out.append(n.model_copy(update={"summary": chosen}))

    _LOG.info(
        "Summarized %s nodes: %s docstring, %s signature, %s ollama, %s cloud",
        len(nodes),
        stats.docstring,
        stats.signature,
        stats.local,
        stats.cloud,
    )

    # Light-weight cost/log signal for callers/tests.
    # (Printing here would be noisy; store in metadata for now.)
    if out:
        out[0].metadata.setdefault(
            "summarization_stats",
            {
                "docstring": stats.docstring,
                "signature": stats.signature,
                "local": stats.local,
                "cloud": stats.cloud,
            },
        )

    return out
