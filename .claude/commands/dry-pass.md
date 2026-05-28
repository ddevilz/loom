# /dry-pass

Dedicated pass to remove repetition and bad code from Loom. 
Run after `/review-all` has produced the issue list, or run standalone to audit a specific file.

The goal is not to rewrite Loom — it's to extract repeated patterns into one place so future fixes happen once, not N times.

---

## What counts as a DRY violation in Loom

1. **FalkorDB connection setup** repeated in multiple files
   → Should be one `get_graph_client()` in `loom/db.py` (or similar), imported everywhere

2. **Error response formatting** in MCP tools
   → If `{"error": str(e), "tool": name}` appears more than once in `mcp/server.py`, extract to `_error_response(tool: str, exc: Exception) -> dict`

3. **Node/edge dict construction**
   → If you're building `{"type": "...", "symbol": "...", "file": "..."}` in multiple places, make a dataclass or TypedDict

4. **Embedding calls** (nomic-embed-text)
   → If `embed(text)` is called from more than one module, it belongs in `loom/embeddings.py`

5. **Cypher query fragments**
   → Partial Cypher strings assembled in multiple places should be named constants or query builder functions

---

## The extraction workflow (one pattern at a time)

```
1. Find all N occurrences of the pattern (use grep or Ask Claude to search)
2. Decide the right home for the extracted helper (new file vs existing module)
3. Write the helper with a proper type signature
4. Write a unit test for the helper in isolation
5. Replace all N callsites
6. Run full suite: pytest tests/ -v --tb=short
7. mypy loom/ — zero new errors
```

Never extract and leave some callsites un-replaced. All or nothing.

---

## What counts as "bad code" to fix

- **Silent returns on error:** `except Exception: return {}` → must raise
- **Boolean trap arguments:** `process(data, True, False)` → use named params or enums
- **Mutable default arguments:** `def f(x, cache={})` → `def f(x, cache=None)`
- **Commented-out code blocks** → delete them (git history exists)
- **Functions over ~40 lines** → split into named sub-functions with clear responsibilities
- **Magic strings** (raw edge type strings like `"IMPLEMENTS"` scattered inline)
   → define as constants: `EDGE_IMPLEMENTS = "IMPLEMENTS"` in `loom/types.py`

---

## Specific targets in Loom

These are confirmed or likely repetition hotspots based on the architecture:

| Pattern | Likely location | Extract to |
|---|---|---|
| FalkorDB client init | `repositories.py`, possibly `incremental.py` | `loom/db.py:get_client()` |
| MCP error dict | `mcp/server.py` (per-tool) | `mcp/server.py:_tool_error()` |
| Edge type strings | `linker/`, `repositories.py`, `mcp/server.py` | `loom/types.py` |
| Embed call | Scattered | `loom/embeddings.py:embed()` |
| Cypher `MATCH (s:Symbol)` boilerplate | `repositories.py` | Named query functions |

---

## Output format

After the pass, report:

```
## Extracted helpers
- loom/db.py:get_client() — consolidated from 3 callsites
- mcp/server.py:_tool_error() — consolidated from 5 callsites

## Bad code removed
- loom/incremental.py:82 — silent except removed, now raises IndexError
- mcp/server.py:114 — dead branch deleted (was unreachable after BUG-4 fix)

## Tests added
- tests/test_db.py:test_get_client_returns_connected_graph
- tests/test_mcp_tools.py:test_tool_error_format

## Suite status
pytest: X passed, 0 failed
mypy: 0 errors
ruff: 0 violations
```
