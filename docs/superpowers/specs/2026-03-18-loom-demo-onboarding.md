# Loom Demo — "The New Dev"

**Date:** 2026-03-18
**Format:** Recorded screencast (A) + live interactive script (B)
**Runtime:** ~4 minutes
**Subject repo:** Loom itself (dogfooding — real graph, real call edges)
**Core wow moment:** An AI agent builds a complete mental model of an unfamiliar codebase in under 60 seconds

---

## 1. Premise

A new engineer joins the team. Their first task: add a new language parser to Loom's ingest pipeline. Before touching anything, they need to understand the architecture — what calls what, what could break, where the entry points are. The demo shows how an MCP-connected agent answers every onboarding question from the live graph.

> **Demo framing:** No code changes are made. This is pure exploration. The wow is that the agent gives confident, accurate answers that would take a new dev days to piece together manually.

---

## 2. Audience layers

| Audience | What they're watching for | Scene that lands it |
|---|---|---|
| Engineers | "Does it actually know my code?" | Scene 2 — semantic search returns `_register_defaults`, not a random hit |
| Engineering managers | "Can this replace onboarding docs?" | Scene 3 — blast radius shows the right test surface before any change |
| Investors | "Is this a product?" | Scene 4 — Cursor answers the same questions, same graph |

---

## 3. Pre-conditions (must be true before recording)

- FalkorDB running locally: `docker run -d -p 6379:6379 --name loom-db falkordb/falkordb`
- `loom analyze . --graph-name loom_repo --force` completed (expect: 1520+ nodes, 4881+ edges)
- `.mcp.json` configured for Claude Code with `graph-name: loom_repo`
- Cursor MCP configured with same server command; verify MCP indicator visible in status bar
- Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- Full dry run completed before hitting record

---

## 4. Scene-by-scene script

### Scene 1 — Setup (0:00–0:20)

**On screen:** Slack mockup, then Claude Code terminal.

> **Slack:** `#eng-onboarding — @newdev — your first task: add Go language support to the ingest pipeline. Start in registry.py.`

**Voiceover:** *"A new dev. An unfamiliar codebase. Let's see how fast Loom gets them up to speed."*

Switch to Claude Code. Type:

> *"I'm new to this codebase. I need to add a new language parser to the ingest pipeline. Before I write anything, help me understand how the language registry works, what I'd be touching, and what could break."*

---

### Scene 2 — Semantic search (0:20–1:30)

**Agent tool calls — shown on screen:**

1. `search_code("language registry ingest parser call tracer")` → returns `LanguageRegistry`, `_register_defaults`, `get_registry`, `LanguageConfig`

**Agent on screen:**
> *"The entry point for language support is `_register_defaults` in `registry.py`. It registers each extension with a parser and an optional `call_tracer`. To add Go support, you'd add a new `LanguageConfig` entry here."*

2. `search_code("language config parser tree sitter extension")` → returns `LanguageConfig` dataclass, `parse_code`

**Agent on screen:**
> *"`LanguageConfig` is a dataclass with three fields: `extensions`, `parse_fn`, and `call_tracer`. The parser is a tree-sitter function. The call tracer is optional — it's what generates CALLS edges in the graph."*

**Voiceover:** *"Two searches. The agent already knows what to build and where."*

---

### Scene 3 — Blast radius before the change (1:30–2:45)

**On screen:** Claude Code continues.

**Agent tool calls:**

3. `get_blast_radius("function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry", depth=3)` → 36 nodes across 3 hops

**Agent on screen:**
> *"Before you change anything: `get_registry` has 36 dependents across 3 hops. The most critical are `parse_code` → `parse_repo` → `index_repo` — that's the entire ingest pipeline. Any change here needs tests that cover the full pipeline, not just registry.py."*

Zoom into the blast tree:

```
get_registry (registry.py)
├─ parse_code (parser.py)          ← calls get_registry
│  ├─ parse_repo (parser.py)       ← calls parse_code
│  │  └─ index_repo (pipeline.py)  ← calls parse_repo
├─ walk_repo (walker.py)           ← calls get_registry
│  └─ parse_repo (parser.py)       ← calls walk_repo
```

**Voiceover:** *"The agent shows the test surface before a single line is written. That's the kind of context that prevents incidents."*

Then cut to terminal and run the raw CLI:

```bash
loom blast_radius \
  --node "function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry" \
  --graph-name loom_repo \
  --depth 3
```

**Voiceover:** *"Same graph. CLI or agent — same answer."*

---

### Scene 4 — Callers and entry points (2:45–3:30)

**Agent tool calls:**

4. `get_callers("function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:_register_defaults")` → lists `get_registry` as the only caller

**Agent on screen:**
> *"`_register_defaults` is only called once — by `get_registry`, which caches the result. This is a singleton pattern. Your new `LanguageConfig` entry goes inside `_register_defaults`, and the graph will pick it up on the next index."*

**Voiceover:** *"From 'I don't know this codebase' to a clear implementation plan — in under 3 minutes."*

---

### Outro (3:30–4:00)

**On screen:** Static split — Slack message on left, blast tree on right.

**Caption:**
> *"Loom gives every new engineer a map of the codebase before they touch anything — not from docs that go stale, but from the live graph."*

**End card:** `github.com/ddevilz/loom  ·  loom serve`

---

## 5. What NOT to show

- Do not show the Docker setup or `loom analyze` run — start with the graph already indexed
- Do not show disambiguation prompts — use full node IDs in all tool calls
- Do not explain COUPLED_WITH or MEMBER_OF edges if they appear — they're enrichment noise for this demo
- Do not show the Go parser implementation — this demo ends at the design stage, not the code stage

---

## 6. Pre-recording verification commands

Run all of these before the dry run. Each must succeed.

```bash
# 1. Verify get_registry blast radius returns ≥ 20 nodes
uv run loom blast_radius \
  --node "function:/Users/devashish/Desktop/loom/src/loom/ingest/code/registry.py:get_registry" \
  --graph-name loom_repo \
  --depth 3

# 2. Verify search returns the right nodes
uv run loom query "language registry ingest parser call tracer" --graph-name loom_repo --limit 5

# 3. Verify _register_defaults has exactly 1 caller (get_registry)
uv run python3 -c "
from loom.core import LoomGraph
import asyncio
async def t():
    g = LoomGraph(graph_name='loom_repo')
    r = await g.query(\"MATCH (a)-[:CALLS]->(b) WHERE b.name = '_register_defaults' RETURN a.name, a.path\", {})
    print(r)
asyncio.run(t())
"

# 4. Verify MCP server starts clean (no stdout pollution)
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
- [ ] Graph indexed (`loom_repo`: 1520+ nodes, 4881+ edges)
- [ ] All 4 verification commands pass
- [ ] Slack mockup screenshot ready
- [ ] Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- [ ] Claude Code `.mcp.json` pointing to `loom_repo`
- [ ] Full dry run completed — every scene runs without error before hitting record
