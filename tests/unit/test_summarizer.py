from __future__ import annotations

import pytest

from loom.analysis.code.summarizer import SummarizationStrategy, is_trivial_change, summarize_nodes
from loom.core import Node, NodeKind, NodeSource


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: int = 0

    async def summarize(self, *, prompt: str, max_tokens: int = 200, model: str | None = None) -> str:
        self.calls += 1
        return "LLM summary"


def _node(node_id: str, *, metadata: dict) -> Node:
    kind_str = node_id.split(":", 1)[0]
    kind = NodeKind(kind_str)
    return Node(
        id=node_id,
        kind=kind,
        source=NodeSource.CODE,
        name="f",
        path="p",
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_summarize_nodes_uses_docstring_no_llm_calls() -> None:
    llm = _FakeLLM()
    n = _node("function:p:f", metadata={"docstring": "hello"})
    out = await summarize_nodes([n], llm=llm)
    assert out[0].summary == "hello"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_docstring_only_strategy_makes_zero_llm_calls() -> None:
    llm = _FakeLLM()
    n = _node("function:p:f", metadata={})
    out = await summarize_nodes([n], llm=llm, strategy=SummarizationStrategy.DOCSTRING_ONLY)
    assert out[0].summary is None
    assert llm.calls == 0


def test_is_trivial_change_whitespace_and_comments() -> None:
    a = """
# comment
x = 1
"""
    b = """

# comment changed
x=1   

"""
    assert is_trivial_change(a, b)


@pytest.mark.asyncio
async def test_auto_strategy_falls_back_to_signature_without_llm() -> None:
    llm = _FakeLLM()
    n = _node("function:p:f", metadata={"signature": "f(x) -> int"})
    out = await summarize_nodes([n], llm=llm, strategy=SummarizationStrategy.AUTO)
    assert out[0].summary == "f(x) -> int"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_smart_invalidation_keeps_previous_summary_on_trivial_change() -> None:
    llm = _FakeLLM()

    old = Node(
        id="function:p:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="p",
        content_hash="old",
        summary="prev summary",
        metadata={"source_text": "# c\nx = 1\n"},
    )
    new = Node(
        id="function:p:f",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="f",
        path="p",
        content_hash="new",
        metadata={"source_text": "# changed\nx=1\n"},
    )

    out = await summarize_nodes([new], llm=llm, previous_nodes=[old])
    assert out[0].summary == "prev summary"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_summarize_nodes_logs_cost_estimate(caplog) -> None:
    caplog.set_level("INFO")
    llm = _FakeLLM()

    n1 = _node("function:p:f", metadata={"docstring": "hello"})
    n2 = _node("function:p:g", metadata={"signature": "g()"})

    await summarize_nodes([n1, n2], llm=llm)

    assert any(
        "Summarized" in r.message and "docstring" in r.message and "signature" in r.message
        for r in caplog.records
    )
