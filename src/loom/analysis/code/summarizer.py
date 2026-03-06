from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from loom.core import Node


_LOG = logging.getLogger(__name__)
_METADATA_DOCSTRING = "docstring"
_METADATA_SIGNATURE = "signature"
_METADATA_PARAMS = "params"
_METADATA_RETURN_TYPE = "return_type"
_METADATA_SOURCE_TEXT = "source_text"
_DEFAULT_LOCAL_MODEL = "llama3.2"
_DEFAULT_CLOUD_MODEL = "gpt-4o-mini"
_SUMMARY_FALLBACK = "{kind} {name} ({path})"
_SUMMARY_PROMPT = "Summarize what this code element does:\n\nName: {name}\nKind: {kind}\nPath: {path}\n"
_SUMMARY_LOG_TEMPLATE = "Summarized %s nodes: %s docstring, %s signature, %s ollama, %s cloud"


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
    doc = node.metadata.get(_METADATA_DOCSTRING)
    if isinstance(doc, str):
        doc = doc.strip()
        return doc or None
    return None


def _signature_from_metadata(node: Node) -> str | None:
    sig = node.metadata.get(_METADATA_SIGNATURE)
    if isinstance(sig, str):
        sig = sig.strip()
        return sig or None

    params = node.metadata.get(_METADATA_PARAMS)
    ret = node.metadata.get(_METADATA_RETURN_TYPE)

    if isinstance(params, list) and all(isinstance(p, str) for p in params):
        ret_s = f" -> {ret}" if isinstance(ret, str) and ret else ""
        return f"{node.name}({', '.join(params)}){ret_s}"

    return None


def _fallback_summary(node: Node) -> str:
    return _SUMMARY_FALLBACK.format(kind=node.kind.value, name=node.name, path=node.path)


def _reusable_previous_summary(node: Node, previous: Node | None) -> str | None:
    if previous is None or previous.summary is None:
        return None
    if previous.content_hash == node.content_hash:
        return previous.summary

    old_src = previous.metadata.get(_METADATA_SOURCE_TEXT)
    new_src = node.metadata.get(_METADATA_SOURCE_TEXT)
    if isinstance(old_src, str) and isinstance(new_src, str) and is_trivial_change(old_src, new_src):
        return previous.summary

    return None


def _record_docstring(stats: SummarizationStats) -> SummarizationStats:
    return SummarizationStats(
        docstring=stats.docstring + 1,
        signature=stats.signature,
        local=stats.local,
        cloud=stats.cloud,
    )


def _record_signature(stats: SummarizationStats) -> SummarizationStats:
    return SummarizationStats(
        docstring=stats.docstring,
        signature=stats.signature + 1,
        local=stats.local,
        cloud=stats.cloud,
    )


def _record_local(stats: SummarizationStats) -> SummarizationStats:
    return SummarizationStats(
        docstring=stats.docstring,
        signature=stats.signature,
        local=stats.local + 1,
        cloud=stats.cloud,
    )


def _record_cloud(stats: SummarizationStats) -> SummarizationStats:
    return SummarizationStats(
        docstring=stats.docstring,
        signature=stats.signature,
        local=stats.local,
        cloud=stats.cloud + 1,
    )


def _select_model(
    *,
    strategy: SummarizationStrategy,
    cloud_threshold: float,
    local_model: str,
    cloud_model: str,
) -> tuple[str, bool]:
    if strategy == SummarizationStrategy.CLOUD or (
        strategy == SummarizationStrategy.AUTO and cloud_threshold > 0.0
    ):
        return cloud_model, True
    return local_model, False


async def _llm_summary(
    node: Node,
    *,
    llm: LLMClient,
    strategy: SummarizationStrategy,
    cloud_threshold: float,
    local_model: str,
    cloud_model: str,
    max_tokens_per_function: int,
    stats: SummarizationStats,
) -> tuple[str, SummarizationStats, bool]:
    model, is_cloud = _select_model(
        strategy=strategy,
        cloud_threshold=cloud_threshold,
        local_model=local_model,
        cloud_model=cloud_model,
    )
    prompt = _SUMMARY_PROMPT.format(name=node.name, kind=node.kind.value, path=node.path)
    summary = await llm.summarize(
        prompt=prompt,
        max_tokens=max_tokens_per_function,
        model=model,
    )
    next_stats = _record_cloud(stats) if is_cloud else _record_local(stats)
    return summary, next_stats, True


async def summarize_nodes(
    nodes: list[Node],
    llm: LLMClient | None = None,
    strategy: SummarizationStrategy = SummarizationStrategy.AUTO,
    previous_nodes: list[Node] | None = None,
    *,
    local_model: str = _DEFAULT_LOCAL_MODEL,
    cloud_model: str = _DEFAULT_CLOUD_MODEL,
    cloud_threshold: float = 0.0,
    max_tokens_per_function: int = 200,
) -> list[Node]:
    stats = SummarizationStats()
    out: list[Node] = []

    prev_by_id: dict[str, Node] = {n.id: n for n in (previous_nodes or [])}

    for n in nodes:
        reused = _reusable_previous_summary(n, prev_by_id.get(n.id))
        if reused is not None:
            out.append(n.model_copy(update={"summary": reused}))
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
            stats = _record_docstring(stats)
        elif strategy == SummarizationStrategy.DOCSTRING_ONLY:
            chosen = None
        elif sig is not None and strategy in {
            SummarizationStrategy.AUTO,
            SummarizationStrategy.SIGNATURE_ONLY,
        }:
            chosen = sig
            stats = _record_signature(stats)
        else:
            if llm is None:
                chosen = _fallback_summary(n)
            else:
                chosen, stats, used_llm = await _llm_summary(
                    n,
                    llm=llm,
                    strategy=strategy,
                    cloud_threshold=cloud_threshold,
                    local_model=local_model,
                    cloud_model=cloud_model,
                    max_tokens_per_function=max_tokens_per_function,
                    stats=stats,
                )

        if chosen is None:
            out.append(n)
            continue

        chosen = chosen.strip()
        if used_llm and not chosen:
            chosen = _fallback_summary(n)

        out.append(n.model_copy(update={"summary": chosen}))

    _LOG.info(
        _SUMMARY_LOG_TEMPLATE,
        len(nodes),
        stats.docstring,
        stats.signature,
        stats.local,
        stats.cloud,
    )

    return out
