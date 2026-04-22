# /fix-and-test

Fix one issue from the review list. Always in this order: test → fix → verify. Never fix first.

---

## The invariant loop (never skip steps)

```
1. Read the broken code
2. Write a test that fails because of the issue        ← RED
3. Run: pytest tests/ -v -k "<test_name>" --tb=short  ← confirm RED
4. Apply the fix (minimal diff — don't touch unrelated code)
5. Run the same test                                   ← GREEN
6. Run full suite: pytest tests/ -v --tb=short        ← no regressions
7. Run: mypy loom/<changed_file>.py                   ← zero new errors
8. Run: ruff check loom/<changed_file>.py             ← zero violations
```

If step 3 is already green (test passes before fix), the test is wrong — rewrite it.
If step 6 introduces regressions, fix those before moving on.

---

## Bug-specific test templates

Use these as starting points. Adapt to the actual code shape.

### BUG-1 — JS/JSX call tracing (`registry.py`)
```python
def test_jsx_has_call_tracer():
    from loom.registry import REGISTRY, EXT_JSX, EXT_JS
    assert REGISTRY[EXT_JSX].call_tracer is not None, "EXT_JSX missing call_tracer"
    assert REGISTRY[EXT_JS].call_tracer is not None,  "EXT_JS missing call_tracer"
```

### BUG-2 — serve flags ignored (`mcp/server.py`)
```python
def test_serve_flags_are_not_silently_ignored():
    # If transport is stdio, --host/--port must not exist on the CLI.
    # If they exist, mcp.run() must receive them.
    from click.testing import CliRunner
    from loom.cli import serve  # adjust import to actual CLI entry
    runner = CliRunner()
    result = runner.invoke(serve, ["--help"])
    # Either host/port are absent from help text (stdio-only is fine)
    # OR they are present and wired through to mcp.run()
    if "--host" in result.output or "--port" in result.output:
        # They're advertised — must be wired. Check the source directly.
        import inspect, loom.cli as cli_mod
        src = inspect.getsource(cli_mod)
        assert "host=host" in src or "port=port" in src, \
            "--host/--port advertised but not passed to mcp.run()"
```

### BUG-3 — top-level igraph import (`repositories.py`)
```python
def test_repositories_imports_without_igraph():
    import importlib, sys
    # Remove igraph from available modules temporarily
    igraph_backup = sys.modules.pop("igraph", None)
    try:
        if "loom.repositories" in sys.modules:
            del sys.modules["loom.repositories"]
        import loom.repositories  # must not raise ImportError
    finally:
        if igraph_backup is not None:
            sys.modules["igraph"] = igraph_backup
```

### BUG-4 — vestigial key in check_drift (`mcp/server.py`)
```python
import pytest
def test_check_drift_has_no_semantic_violations_key():
    # Import the handler directly and call it with a minimal fixture
    from loom.mcp.server import check_drift  # adjust to actual import
    # You may need to mock FalkorDB — that's fine, just assert on the response shape
    # At minimum: the key must not exist in the return type annotation or response dict
    import inspect
    src = inspect.getsource(check_drift)
    assert "semantic_violations" not in src, \
        "check_drift still contains vestigial semantic_violations key"
```

---

## DRY fix pattern

When extracting repeated logic:

1. Identify all N occurrences of the pattern
2. Write a single shared helper (in the most appropriate module — usually `loom/utils.py`)
3. Write a test that imports and exercises the helper directly
4. Replace all N occurrences with the helper call
5. Run full suite — each previously-passing test that used the pattern still passes

Do NOT inline the fix into just one callsite and leave the others. Fix all N at once.

---

## When the fix is done

Say: "Fixed. Test is green, full suite passes, mypy and ruff clean. Ready for next issue — or run `/test-mcp` to verify the MCP server end-to-end."
