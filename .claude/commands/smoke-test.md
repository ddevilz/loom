Run a full smoke test of the Loom v0.1 launch checklist. Work through each step and report pass/fail.

## Smoke Test Checklist

### 1. Install check
```bash
pip install -e ".[dev]"
loom --version
```
Expected: clean install, version printed.

### 2. BUG-1 regression — JS/JSX call tracer
Open `registry.py`. Confirm `EXT_JS` and `EXT_JSX` both have `call_tracer=trace_calls_for_ts_file` (not `None`).

### 3. BUG-2 regression — serve flags
Open `mcp/server.py`. Confirm either:
- `mcp.run()` uses the `host`/`port` arguments, OR
- `--host`/`--port` CLI options have been removed entirely.
There must be no code path where the flags are printed but silently discarded.

### 4. BUG-3 regression — igraph import
Open `repositories.py`. Confirm `import igraph` does NOT appear at the top-level (lines 1–15). It must only appear inside `_rank_by_personalized_pagerank()`.

### 5. BUG-4 regression — check_drift response
Open `mcp/server.py`. Search for `semantic_violations`. It must not appear in the `check_drift` return dict.

### 6. Type check
```bash
mypy loom/
```
Expected: zero errors.

### 7. Lint
```bash
ruff check loom/
```
Expected: zero violations.

### 8. Test suite
```bash
pytest tests/ -v -x --tb=short
```
Expected: all pass.

### 9. MCP server starts
```bash
timeout 5 loom serve || true
```
Expected: server starts without immediate crash (stdio transport is expected to block/wait).

## Report
After each step, output one line: `✅ PASS` or `❌ FAIL: <reason>`.
At the end, output a summary table of all 9 steps.
If any step fails, do not auto-fix — report and stop.
