---
description: Known issues and recovery notes
---

# Manual Intervention Errors

## Database schema migration failed

### Symptom

```
OperationalError: no such column: summary_hash
```

or similar missing column error.

### Cause

DB was created by an older version of Loom before the column was added.
`_add_column_if_missing()` should handle this automatically on next `loom analyze`,
but may fail if the DB is locked or corrupted.

### Fix

Run `loom analyze .` — schema migration runs automatically via `init_schema()`.

If the error persists, delete and rebuild the DB:
```bash
rm ~/.loom/loom.db
loom analyze .
```

All agent-written summaries will be lost. Auto-summaries will be regenerated.

---

## `loom analyze` reports 0 files changed but index is empty

### Symptom

`loom analyze .` completes immediately with `0 changed, 0 nodes` on a fresh install.

### Cause

The DB has stale hashes from a different repo at the same DB path.

### Fix

Delete the DB and re-index:
```bash
rm ~/.loom/loom.db
loom analyze .
```

Or use a per-project DB:
```bash
loom --db ./.loom/project.db analyze .
```

---

## `loom serve` / MCP connection fails

### Symptom

MCP client shows "server disconnected" or tool calls return errors immediately.

### Cause

Usually one of:
1. `loom` binary not on PATH (MCP config uses `loom serve` but `loom` not found)
2. DB path mismatch between CLI and MCP config

### Fix

Use `uvx loom-tool` in MCP config — works without `loom` on PATH:
```json
{
  "mcpServers": {
    "loom": {
      "command": "uvx",
      "args": ["loom-tool"]
    }
  }
}
```

Or run `loom install` to regenerate the correct config automatically.

---

## `git commit` hook fires but sync fails silently

### Symptom

Post-commit hook runs but nodes not updated after commit.

### Cause

`loom sync` requires the `loom` binary on PATH. If the virtualenv is not activated,
`loom` may not be found.

### Fix

Reinstall the hook with the full binary path:
```bash
loom install --repo .
```

The hook now uses `loom` as installed by pip/uv. If using a virtualenv, activate it
before installing so the hook captures the correct path.

---

## FTS5 search returns no results

### Symptom

`loom query "function_name"` returns nothing, but `loom stats` shows nodes exist.

### Cause

FTS5 virtual table `nodes_fts` may be out of sync with `nodes` table.

### Fix

Rebuild the index:
```bash
loom analyze .
```

`replace_file()` in `store/nodes.py` syncs FTS5 via triggers on every analyze.

---

## Community detection fails with `ModuleNotFoundError`

### Symptom

```
ModuleNotFoundError: No module named 'community'
```

### Cause

`python-louvain` package not installed. It provides the `community` module.

### Fix

```bash
uv add python-louvain
# or:
pip install python-louvain
```

Communities are optional — `loom analyze` continues without them and logs a warning.
