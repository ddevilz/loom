# ADR-0001: Loom Plugin Contract

**Status:** Accepted  
**Date:** 2026-05-05  
**Author:** Devashish  

---

## Context

Loom is a persistent symbol index for AI coding agents. It indexes a codebase once with tree-sitter, stores nodes and edges in SQLite, and lets agents search by keyword to get summaries and signatures instantly — without reading source files. Agents write summaries back via `store_understanding`, enriching the index across sessions.

This ADR defines the plugin contract: what surfaces Loom exposes, what namespaces it owns, how verification works, and the trade-offs accepted.

---

## Decision

### MCP Server Contract

**Server name:** `loom`  
**Transport:** stdio  
**Install:** `uvx --from loom-tool loom-mcp` (no pip install required)  
**DB path:** auto-resolved: `LOOM_DB_PATH` env → `~/.loom/projects/{git-root-name}.db` (inside a git repo) → `~/.loom/loom.db` (global fallback)  
**Auto-index:** if DB is empty, `loom-mcp` indexes the current directory in background before serving

**Tools (21):**

| Tool | Purpose |
|------|---------|
| `search_code(query, limit)` | FTS5 search — returns summary + signature if cached |
| `get_node(node_id)` | Single node lookup |
| `get_context(node_id)` | Full context packet: summary, signature, callers, callees, staleness |
| `get_callers(node_id)` | One-hop incoming CALLS |
| `get_callees(node_id)` | One-hop outgoing CALLS |
| `get_blast_radius(node_id, depth)` | Transitive callers via recursive CTE |
| `get_neighbors(node_id, depth)` | All edges, both directions |
| `get_community(community_id)` | Community member nodes |
| `shortest_path(from_id, to_id)` | Shortest CALLS path |
| `graph_stats()` | Node/edge counts by kind |
| `god_nodes(limit)` | Most-called functions |
| `store_understanding(node_id, summary, force)` | Write agent summary to SQLite |
| `store_understanding_batch(updates)` | Batch summary writes (max 50) |
| `get_savings()` | Token savings report |
| `get_status()` | Node count + DB health check |
| `start_session(agent_id)` | Register session, returns session_id + unannotated_reads + annotation_gaps |
| `get_delta(previous_session_id, agent_id)` | Changed nodes since last session |
| `get_surprising_connections(limit)` | Non-obvious cross-module CALLS edges |
| `suggest_questions(limit)` | Graph-topology-based investigation priorities |
| `get_community_cohesion()` | Cohesion scores per cluster |
| `get_work_plan()` | Prioritized action list: DOCUMENT / INVESTIGATE / EXPLORE / NOTHING |

**Resources (2):**
- `loom://primer` — 200-token compressed codebase overview (session start)
- `loom://savings` — token savings report

### Agent Contract

Three agents, each with explicit tool allow-lists:

- **navigator** — code exploration (search + context + traversal tools)
- **summarizer** — documentation (search + context + store_understanding tools)
- **analyst** — impact analysis (blast radius + topology tools)

No agent has wildcard tool access.

### Skill Contract

Four skills, each with minimal allowed-tool lists:

- **onboard** — first-time repo setup
- **explore-code** — codebase navigation
- **impact-analysis** — change risk assessment
- **document-code** — summary writing

### Namespace Convention

Loom owns:
- MCP server name: `loom`
- MCP tool prefix: `mcp__loom__*`
- DB default (git repos): `~/.loom/projects/{git-root-name}.db`
- DB fallback (non-git): `~/.loom/loom.db`
- Config key: `loom` in `mcpServers`

Does NOT claim:
- Any other MCP server names
- Any file system paths outside `~/.loom/`
- Any Claude Code settings keys

### Smoke Test Contract

`scripts/smoke.sh` verifies:
1. `plugin.json` declares version 0.5.0 with required keywords
2. `mcpServers.loom` entry uses `uvx --from loom-tool loom-mcp`
3. All 3 agents present with valid YAML frontmatter
4. All 4 skills present with `allowed-tools` explicitly defined
5. No skill grants wildcard (`*`) tool access
6. All 7 commands present (loom-analyze, loom-context, loom-summaries, loom-blast, loom-delta, loom-topology, loom-savings)
7. ADR-0001 exists with status "Accepted"
8. README documents install and quick-start workflow
9. `loom://primer` and `loom://savings` resources documented in README
10. `uvx --from loom-tool loom-mcp --version` exits 0 (MCP server is installable)

---

## Consequences

### Positive

- **Zero install friction** — `uvx` resolves `loom-tool` on demand; no pip install required
- **Zero LLM cost** — tree-sitter indexing is deterministic; summaries are human/agent-written
- **Accumulating value** — every `store_understanding` call makes future sessions cheaper
- **Auto-index** — resolved DB empty on first session → MCP server indexes current dir in background → no manual step

### Negative

- **Cold-start latency** — first `loom analyze` takes 5–30s on large repos (one-time cost)
- **DB drift** — if post-commit hook isn't installed, DB can go stale (mitigated by `loom install`)
- **Single DB** — concurrent write access from multiple agents requires WAL mode (already enabled)

### Neutral

- **uvx requirement** — assumes `uv` is installed. Alternative: `pip install loom-tool && loom-mcp`
- **stdio transport** — standard MCP protocol, compatible with all MCP-supporting tools

---

## Verification

```bash
bash plugins/loom-plugin/scripts/smoke.sh
# Expected: 10 passed, 0 failed
```
