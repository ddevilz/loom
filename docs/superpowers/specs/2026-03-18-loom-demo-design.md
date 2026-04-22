# Loom Demo Design — "The Incident"

**Date:** 2026-03-18
**Format:** Recorded screencast (A) + live interactive script (B)
**Runtime:** ~5 minutes
**Subject repo:** Loom itself (dogfooding — real Jira tickets, real graph)
**Core wow moment:** MCP agent (Claude Code + Cursor) reasoning over a live knowledge graph

---

## 1. Premise

A Jira ticket lands: LOOM-1, JS/JSX call tracing broken — call graph missing JS callers. The demo shows the full investigation workflow:

1. **Where exactly is it?** — agent reads the ticket, searches the graph
2. **What's the blast radius?** — agent calls `get_blast_radius`, shows the tree
3. **Is the fix safe?** — agent verifies callers, checks ticket links, reviews the diff

> **Demo staging note:** LOOM-1 is already fixed in the current codebase. The demo is played as an investigation of a recently merged fix — "the ticket came in, a dev made a change, now we verify the fix is complete and the blast radius is understood before closing the ticket." This framing is honest (the fix exists) and still shows every tool working as intended.

---

## 2. Audience layers

| Audience | What they're watching for | Scene that lands it |
|---|---|---|
| Engineers | "Does the data actually match my codebase?" | Scene 3 — blast tree matches `registry.py` reality |
| Investors | "Is this a real product with a real use case?" | Scene 2 + Outro — agent solves an incident, split-screen closes it |
| AI agent builders | "Can I plug this into my own agent?" | Scene 4 — Cursor makes the same calls, same graph |

---

## 3. Pre-conditions (must be true before recording)

- FalkorDB running locally: `docker run -d -p 6379:6379 --name loom-db falkordb/falkordb`
- Embedding model pre-warmed (prevents first-call delay):
  ```bash
  uv run python3 -c "from fastembed import TextEmbedding; TextEmbedding('nomic-ai/nomic-embed-text-v1.5')"
  ```
- `loom analyze . --graph-name loom_repo --force` completed (expect: 1520 nodes, 4881 edges, 48 tickets)
- `loom enrich --graph-name loom_repo` completed — runs in background, never shown in demo
- `.mcp.json` configured for Claude Code with `graph-name: loom_repo`
- Cursor MCP configured with same server command; verify MCP indicator visible in status bar before recording
- Slack mockup screenshot saved at `/tmp/loom-demo-slack.png`
- Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- Full dry run completed before hitting record

---

## 4. Scene-by-scene script

### Scene 1 — Index (0:00–0:30)

**On screen:** Clean terminal.

```bash
loom analyze . --graph-name loom_repo --force
```

Let progress lines roll. Cut to output (two separate tables in actual CLI):

```
┌───────────────┬────────┐
│ file_count    │ 193    │
│ nodes         │ 1520   │
│ edges         │ 4881   │
│ errors        │ 0      │
└───────────────┴────────┘
┌──────────────┬────┐
│ jira_tickets │ 48 │
└──────────────┴────┘
```

**Voiceover:** *"One command. Your entire codebase — every function, every call relationship, every Jira ticket — is now a queryable graph."*

> **Narrator note:** The `434s` runtime is the actual index time. The "one command" framing is about simplicity, not speed. If asked about the 7-minute time, note that incremental re-indexing takes 16s.

---

### Scene 2 — The incident (0:30–1:30) — Claude Code

**On screen:** Slack mockup, then Claude Code terminal.

> **Slack:** `#eng-alerts — LOOM-1: JS/JSX call tracing not wired. Call graph missing JS callers.`

Switch to Claude Code. Type:

> *"LOOM-1 was just resolved. I want to verify the fix is complete and understand what was at risk. Read the ticket, find the impacted code, and show me the blast radius."*

**Agent tool calls — shown on screen as they execute:**

1. `get_ticket("LOOM-1")` → returns ticket: *"JS/JSX call tracing not wired in registry.py. EXT_JS and EXT_JSX had call_tracer=None."*
2. `search_code("JS JSX call tracer language registry")` → returns `LanguageRegistry`, `get_registry`, `_register_defaults`
3. `get_blast_radius("function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry", depth=3)` → 36 nodes across 3 hops

**Voiceover:** *"Three tool calls. The agent reads the ticket, locates the code, then asks the graph: what depends on this?"*

---

### Scene 3 — The blast tree (1:30–3:00)

**On screen:** Claude Code response, then raw CLI.

Zoom into the agent's output. The blast tree shows callers — each entry is a node that calls (directly or transitively) into `get_registry`. The `← CALLS` label means "this node calls its parent":

```
Blast radius: 36 nodes across 3 hops

get_registry (registry.py)
├─ parse_code (parser.py)          ← calls get_registry
│  ├─ parse_repo (parser.py)       ← calls parse_code
│  │  └─ index_repo (pipeline.py)  ← calls parse_repo  (entire ingest pipeline)
├─ walk_repo (walker.py)           ← calls get_registry
│  └─ parse_repo (parser.py)       ← calls walk_repo
│     └─ _build_file_batch (incremental.py)  ← calls parse_repo
```

**Agent on screen:**
> *"36 functions depended on `get_registry`. The fix touched the right node — but the blast radius confirms that `parse_code`, `walk_repo`, `parse_repo`, and `index_repo` all needed to be stable after the change. That's the test surface and the prod watchlist."*

Then cut to terminal, run the raw CLI command:

```bash
loom blast_radius \
  --node "function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry" \
  --graph-name loom_repo \
  --depth 3
```

**Voiceover:** *"The agent and the CLI see the same graph. Real edges from real AST parsing."*

> **Narrator note:** If the blast radius count differs from 36, any count ≥ 20 is still impressive. The exact number depends on graph state at recording time.

---

### Scene 4 — Cursor handoff (3:00–4:30)

**On screen:** Cursor IDE, MCP indicator visible, `registry.py` open.

Ask Cursor (the agent must resolve the full node id — show the `search_code` call happening first, then the downstream calls):

> *"Verify the LOOM-1 fix in registry.py. Who calls `get_registry`? Is this function linked to any open tickets? And is there any recorded drift?"*

**Cursor tool calls — shown in agent panel:**

1. `search_code("get_registry registry language handler")` → resolves full node id
2. `get_callers("function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry")` → lists `parse_code`, `walk_repo`, `_trace_calls_for_path`
3. `get_impact("LOOM-1")` → returns code nodes linked to LOOM-1 (confirms `get_registry` area is linked)
4. `check_drift("function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry")` → `{"ast_drift": []}` — no recorded violation

Cursor response confirms the fix is clean: callers are accounted for, LOOM-1 is linked, no drift.

**Voiceover:** *"Same graph. Different editor. Claude Code in the terminal, Cursor in the IDE — any MCP-compatible client gets the same intelligence."*

---

### Outro (4:30–5:00)

**On screen:** Static split-screen — LOOM-1 Jira ticket on left, blast tree on right.

**Caption:**
> *"Loom connects your tickets, code, and docs into one graph — and gives every AI agent a map before they touch anything."*

**End card:** `github.com/ddevilz/loom  ·  loom serve`

---

## 5. What NOT to show

- Do not show `loom watch` — real-time updates are impressive but distract from the core story
- Do not show the Docker setup — start at `loom analyze`
- Do not show disambiguation prompts — use full node IDs in all tool and CLI calls
- Do not show `loom enrich` — it ran in background; if asked about communities/coupling, note it's available but not needed for the incident workflow
- Do not explain the COUPLED_WITH or MEMBER_OF edges if they appear in any query output — they are background enrichment, not part of this story

---

## 6. Pre-recording verification commands

Run all of these before the dry run. Each must succeed.

```bash
# 1. Verify LOOM-1 ticket is in graph
uv run python3 -c "
from loom.core import LoomGraph
import asyncio
async def t():
    g = LoomGraph(graph_name='loom_repo')
    r = await g.query(\"MATCH (n) WHERE n.name = 'LOOM-1' RETURN n.name, n.summary LIMIT 1\", {})
    print(r)
asyncio.run(t())
"

# 2. Verify get_registry blast radius (expect ≥ 20 nodes)
uv run loom blast_radius \
  --node "function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry" \
  --graph-name loom_repo \
  --depth 3

# 3. Verify get_impact returns code nodes for LOOM-1
uv run python3 /tmp/test_mcp_all.py  # or use Claude Code: get_impact("LOOM-1")

# 4. Verify search_code returns get_registry-area nodes
uv run loom query "JS JSX call tracer language registry" --graph-name loom_repo --limit 5

# 5. Verify MCP server starts clean (no stdout pollution)
uv run python3 -c "
import asyncio
from fastmcp.client import Client
from fastmcp.client.transports.stdio import StdioTransport
async def t():
    transport = StdioTransport(command='uv', args=['run','loom','serve','--graph-name','loom_repo'], cwd='/Users/devashish/Desktop/loom')
    async with Client(transport) as c:
        tools = await c.list_tools()
        print(f'MCP OK: {len(tools)} tools')
asyncio.run(t())
"
```

---

## 7. Recording checklist

- [ ] FalkorDB running (`docker ps` shows `loom-db`)
- [ ] Embedding model pre-warmed (run pre-warm command above)
- [ ] Graph indexed (`loom_repo`: 1520+ nodes, 4881+ edges, 48 tickets)
- [ ] All 5 verification commands in Section 6 pass
- [ ] Slack mockup screenshot ready at `/tmp/loom-demo-slack.png`
- [ ] Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- [ ] Claude Code `.mcp.json` pointing to `loom_repo`
- [ ] Cursor MCP configured, server connected, MCP indicator visible in status bar
- [ ] Audio: quiet room, mic tested, no background notifications
- [ ] Screen recorder: OBS or Quicktime, 1920×1080 minimum
- [ ] Full dry run completed — every scene runs without error before hitting record
