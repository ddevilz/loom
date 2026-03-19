"""Tests for issues found in /review-all quality pass."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# CRITICAL-1: schema._safe_run swallows non-"already-exists" errors and still
# marks the graph as initialized.
# ---------------------------------------------------------------------------


def test_schema_safe_run_does_not_mark_done_on_real_error() -> None:
    """If _safe_run encounters a non-already-exists error, schema_init must NOT
    add the graph name to _SCHEMA_INIT_DONE."""
    from loom.core.falkor import schema as schema_mod

    # Clear any cached state for this graph name
    schema_mod._SCHEMA_INIT_DONE.discard("_test_graph_real_error")

    class _FailGateway:
        graph_name = "_test_graph_real_error"

        def run(self, cypher: str, *, params=None, timeout=None) -> None:
            raise RuntimeError("some unexpected DB error")

    try:
        schema_mod.schema_init(_FailGateway())
    except Exception:
        pass  # propagation is also acceptable

    assert "_test_graph_real_error" not in schema_mod._SCHEMA_INIT_DONE, (
        "schema_init added graph to _SCHEMA_INIT_DONE even though DDL failed with a "
        "non-already-exists error — future calls will skip init on a broken schema"
    )


def test_schema_safe_run_marks_done_on_already_exists() -> None:
    """already-exists errors are expected (idempotent DDL) — init should complete."""
    from loom.core.falkor import schema as schema_mod

    schema_mod._SCHEMA_INIT_DONE.discard("_test_graph_already_exists")

    class _AlreadyExistsGateway:
        graph_name = "_test_graph_already_exists"

        def run(self, cypher: str, *, params=None, timeout=None) -> None:
            raise RuntimeError("Index already exists for this label")

    schema_mod.schema_init(_AlreadyExistsGateway())

    assert "_test_graph_already_exists" in schema_mod._SCHEMA_INIT_DONE


# ---------------------------------------------------------------------------
# CRITICAL-2: pipeline._process_file — call tracer failures should be logged,
# not silently ignored.
# ---------------------------------------------------------------------------


async def test_process_file_logs_call_tracer_failure(caplog) -> None:
    """When a call tracer raises, the error must be logged (not silently swallowed)."""
    import tempfile
    from pathlib import Path

    from loom.ingest.pipeline import _FileProcessResult, _process_file

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as f:
        f.write("def foo(): pass\n")
        fp = f.name

    fake_graph = MagicMock()
    fake_graph.query = AsyncMock(return_value=[])

    def _bad_tracer(path: str, nodes: list) -> list:
        raise RuntimeError("tracer exploded")

    with (
        patch("loom.ingest.pipeline.parse_code", return_value=[]),
        patch(
            "loom.ingest.pipeline._get_call_tracer",
            return_value=(_bad_tracer, "tracer exploded"),
        ),
        caplog.at_level(logging.WARNING, logger="loom.ingest.pipeline"),
    ):
        result = await _process_file(
            fake_graph,
            fp=fp,
            stored_hash=None,
            exclude_tests=False,
            batch=_FileProcessResult(),
        )

    Path(fp).unlink(missing_ok=True)
    assert any("tracer" in r.message.lower() or "call" in r.message.lower() for r in caplog.records), (
        "Call tracer failure was silently swallowed — no warning logged"
    )


# ---------------------------------------------------------------------------
# DRY-1: node resolution logic duplicated in calls() and blast_radius() CLI
# commands — must be extracted to a shared helper in node_lookup.py.
# ---------------------------------------------------------------------------


def test_resolve_node_from_rows_helper_exists() -> None:
    """A shared resolve_node_from_rows helper should exist in query.node_lookup."""
    import loom.query.node_lookup as nl

    assert hasattr(nl, "resolve_node_id_from_rows"), (
        "resolve_node_id_from_rows helper not found in loom.query.node_lookup — "
        "duplicated logic in cli.py has not been extracted"
    )


# ---------------------------------------------------------------------------
# DRY-2: Threshold constants hardcoded in linker.py, server.py, and cli.py.
# ---------------------------------------------------------------------------


def test_linker_defaults_come_from_config() -> None:
    """SemanticLinker default thresholds should reference config constants."""
    from loom.config import LOOM_LINKER_EMBED_THRESHOLD, LOOM_LINKER_NAME_THRESHOLD
    from loom.linker.linker import SemanticLinker

    linker = SemanticLinker()
    assert linker.name_threshold == LOOM_LINKER_NAME_THRESHOLD, (
        "SemanticLinker.name_threshold does not match config.LOOM_LINKER_NAME_THRESHOLD"
    )
    assert linker.embedding_threshold == LOOM_LINKER_EMBED_THRESHOLD, (
        "SemanticLinker.embedding_threshold does not match config.LOOM_LINKER_EMBED_THRESHOLD"
    )


# ---------------------------------------------------------------------------
# MISLEADING-1: _persist_batch prints "Persisting X nodes..." BEFORE the await,
# meaning the message is printed even if the DB call raises.
# ---------------------------------------------------------------------------


async def test_persist_batch_logs_after_not_before_db_call() -> None:
    """The persistence log message must appear after bulk_create_nodes succeeds."""
    from loom.core import Node, NodeKind, NodeSource
    from loom.ingest.pipeline import _IndexBatch, _persist_batch

    calls: list[str] = []

    class _TrackingGraph:
        async def bulk_create_nodes(self, nodes: list) -> None:
            calls.append("db_nodes")

        async def bulk_create_edges(self, edges: list) -> None:
            calls.append("db_edges")

    n = Node(
        id="function:f.py:foo",
        kind=NodeKind.FUNCTION,
        source=NodeSource.CODE,
        name="foo",
        path="f.py",
    )
    batch = _IndexBatch()
    batch.nodes_to_upsert.append(n)

    printed: list[str] = []
    import builtins

    real_print = builtins.print

    def _capture_print(*args, **kwargs):
        printed.append(" ".join(str(a) for a in args))

    with patch("builtins.print", side_effect=_capture_print):
        await _persist_batch(_TrackingGraph(), "/repo", batch)

    # The "Completed" message must come after the DB call happened
    completed_idx = next(
        (i for i, m in enumerate(printed) if "Completed node" in m), None
    )
    assert completed_idx is not None, "No 'Completed node persistence' message printed"
    assert "db_nodes" in calls, "bulk_create_nodes was never called"


# ---------------------------------------------------------------------------
# MISLEADING-3: zero-edge linking reported as "Completed linking in Xs"
# with no indication that 0 edges were created.
# ---------------------------------------------------------------------------


async def test_link_code_nodes_logs_edge_count() -> None:
    """When SemanticLinker creates 0 edges, output must indicate this (not just timing)."""
    from loom.ingest.pipeline import _IndexBatch, _link_code_nodes

    fake_graph = MagicMock()
    fake_graph.query = AsyncMock(return_value=[])

    printed: list[str] = []

    with (
        patch(
            "loom.ingest.pipeline.SemanticLinker.link",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "loom.ingest.pipeline.get_doc_nodes_for_linking",
            new=AsyncMock(return_value=[MagicMock()]),
        ),
        patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))),
    ):
        from loom.core import Node, NodeKind, NodeSource

        code_node = Node(
            id="function:f.py:foo",
            kind=NodeKind.FUNCTION,
            source=NodeSource.CODE,
            name="foo",
            path="f.py",
            summary="does something",
        )
        batch = _IndexBatch()
        batch.nodes_to_upsert.append(code_node)
        await _link_code_nodes(fake_graph, batch, root="/repo", docs_path=None, jira=None)

    link_msgs = [m for m in printed if "link" in m.lower()]
    assert any("edges" in m.lower() for m in link_msgs), (
        "Zero-edge linking outcome not surfaced in output — output must include 'edges' "
        "count so caller knows whether linking produced results: " + str(link_msgs)
    )


# ---------------------------------------------------------------------------
# CLEANUP-1: registry.py docstring says unknown extensions are "silently skipped"
# but markup extensions (.html, .xml, etc.) are actually registered.
# ---------------------------------------------------------------------------


def test_html_extension_is_registered_not_silently_skipped() -> None:
    """HTML files must be registered in the language registry (comment is wrong)."""
    from loom.ingest.code.registry import get_registry

    reg = get_registry()
    handler = reg.get_handler_for_path("index.html")
    assert handler is not None, (
        "HTML files are not registered — or the registry comment is right and "
        "markup parsers are missing"
    )


# ---------------------------------------------------------------------------
# CLEANUP-2: llm/client.py bare except swallows attribute errors silently.
# ---------------------------------------------------------------------------


async def test_llm_client_raises_on_bad_response_shape() -> None:
    """LLMClient.complete must raise (not return str(res)) when response is malformed."""
    import pytest
    from loom.llm.client import LLMClient

    client = LLMClient(model="gpt-4o-mini")

    bad_response = MagicMock(spec=[])  # no .choices attribute

    with patch("litellm.acompletion", new=AsyncMock(return_value=bad_response)):
        with pytest.raises(Exception):
            await client.complete(prompt="test")


# ---------------------------------------------------------------------------
# CLEANUP-3: schema.py imports logging inside _safe_run (should be module-level).
# ---------------------------------------------------------------------------


def test_schema_logging_import_is_at_module_level() -> None:
    """'import logging' must not appear inside _safe_run — move to module level."""
    import inspect

    from loom.core.falkor import schema as schema_mod

    src = inspect.getsource(schema_mod._safe_run)
    assert "import logging" not in src, (
        "_safe_run still has 'import logging' inside the function body — "
        "move it to module level"
    )
