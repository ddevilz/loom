# Loom Demo — "The PM's Question"

**Date:** 2026-03-18
**Format:** Recorded screencast (A) + live interactive script (B)
**Runtime:** ~4 minutes
**Subject repo:** Loom itself (dogfooding — real Jira tickets, real graph)
**Core wow moment:** A PM-level question ("is this ticket done?") gets a precise code-level answer in 3 tool calls

---

## 1. Premise

A PM asks: *"Is LOOM-7 implemented? I need to know before I close the sprint."* LOOM-7 is the AST drift detection ticket. The demo shows how an MCP agent moves from a Jira key to the exact code that implements it — and flags any related work that's still unlinked.

> **Demo framing:** The answer is "yes, it's implemented" — the fix exists and the graph has the links. The demo is about the journey from question to evidence: no code reading, no grep, no asking the dev who wrote it. The graph knows.

---

## 2. Audience layers

| Audience | What they're watching for | Scene that lands it |
|---|---|---|
| PMs / engineering managers | "Can I trust this answer without reading code?" | Scene 2 — `get_impact` returns exact file paths |
| Engineers | "Does the graph actually reflect reality?" | Scene 3 — `check_drift` confirms no AST divergence |
| Investors | "Is this a product or a prototype?" | Scene 4 — Cursor makes the same calls, closes the loop |

---

## 3. Pre-conditions (must be true before recording)

- FalkorDB running locally: `docker run -d -p 6379:6379 --name loom-db falkordb/falkordb`
- `loom analyze . --graph-name loom_repo --force` completed with Jira:
  ```bash
  loom analyze . --graph-name loom_repo --force \
    --jira-project LOOM \
    --jira-url https://devaloom.atlassian.net \
    --jira-email jadhavom263@gmail.com \
    --jira-token $LOOM_JIRA_API_TOKEN
  ```
- `loom relink --graph-name loom_repo` completed (LOOM_IMPLEMENTS edges populated)
- `.mcp.json` configured for Claude Code with `graph-name: loom_repo`
- Cursor MCP configured with same server command; verify MCP indicator visible
- Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- Full dry run completed before hitting record

---

## 4. Scene-by-scene script

### Scene 1 — The question (0:00–0:30)

**On screen:** Slack mockup, then Claude Code terminal.

> **Slack:** `#eng-pm — Hey team, sprint review is tomorrow. Is LOOM-7 (AST drift detection) actually implemented? Which files does it touch? I need to know before I close it.`

**Voiceover:** *"A PM question. Normally this means pinging a dev, waiting, maybe reading a PR. With Loom, the graph already knows."*

Switch to Claude Code. Type:

> *"LOOM-7 — AST drift detection. Is it implemented? Which code does it touch, and is there anything related that's still unlinked?"*

---

### Scene 2 — Ticket to code (0:30–2:00)

**Agent tool calls — shown on screen as they execute:**

1. `get_ticket("LOOM-7")` → returns ticket:
   ```
   Key: LOOM-7
   Summary: AST drift detection broken — baseline lost on restart (BUG-074)
   Status: Done
   Description: The drift detector loses its baseline node snapshot on DB restart.
                check_drift always returns drifted=false after a restart.
   ```

2. `get_impact("LOOM-7")` → returns code nodes linked to LOOM-7:
   ```
   drift/detector.py → check_drift
   mcp/server.py     → check_drift (MCP tool)
   ```

**Agent on screen:**
> *"LOOM-7 is marked Done. The graph shows it's implemented in `drift/detector.py` — specifically the `check_drift` function — and exposed via the MCP server. The fix landed in both the core logic and the agent interface."*

**Voiceover:** *"Ticket key → exact files → confirmation. No PRs to scroll, no dev to ping."*

---

### Scene 3 — Drift check (2:00–3:00)

**On screen:** Claude Code continues.

**Agent tool calls:**

3. `check_drift("function:/Users/devashish/Desktop/loom/src/loom/drift/detector.py:check_drift")` → returns:
   ```json
   {
     "file": "drift/detector.py",
     "drifted": false,
     "ast_drift": []
   }
   ```

**Agent on screen:**
> *"No AST drift. The indexed snapshot of `check_drift` matches the current file state — meaning the graph's picture of this function is accurate right now, not stale from a previous run."*

Then run the raw CLI to show it's not magic:

```bash
loom query "AST drift detection baseline" --graph-name loom_repo --limit 5
```

**Voiceover:** *"The graph doesn't just store what was true at index time. It can verify it's still true now."*

---

### Scene 4 — Unimplemented check (3:00–3:30)

**On screen:** Claude Code continues.

**Agent tool calls:**

4. `unimplemented()` → returns tickets with no linked code

**Agent on screen:**
> *"For completeness — here are tickets in the graph with no code links yet. LOOM-7 is not on this list. The sprint review is clean."*

**Voiceover:** *"Three seconds to answer the PM's question. The graph knows what's done and what isn't."*

---

### Outro (3:30–4:00)

**On screen:** Static split — LOOM-7 Jira ticket on left, `get_impact` output on right.

**Caption:**
> *"Loom connects your tickets to your code — so every stakeholder gets a precise answer, not a best guess."*

**End card:** `github.com/ddevilz/loom  ·  loom serve`

---

## 5. What NOT to show

- Do not show the Jira indexing run — start with the graph already populated
- Do not show the `relink` step — it ran in the background; LOOM_IMPLEMENTS edges are already there
- Do not explain the COUPLED_WITH or MEMBER_OF edges if they appear in any output
- Do not show tickets that have no LOOM_IMPLEMENTS links unless using `unimplemented` to make that the point
- Do not show `check_drift` failing — use the clean, passing output to close the loop

---

## 6. Pre-recording verification commands

Run all of these before the dry run. Each must succeed.

```bash
# 1. Verify LOOM-7 is in the graph with correct summary
uv run python3 -c "
from loom.core import LoomGraph
import asyncio
async def t():
    g = LoomGraph(graph_name='loom_repo')
    r = await g.query(\"MATCH (n) WHERE n.name = 'LOOM-7' RETURN n.name, n.summary LIMIT 1\", {})
    print(r)
asyncio.run(t())
"

# 2. Verify get_impact returns code nodes for LOOM-7
uv run python3 -c "
from loom.core import LoomGraph
from loom.query.traceability import impact_of_ticket
import asyncio
async def t():
    g = LoomGraph(graph_name='loom_repo')
    nodes = await impact_of_ticket('LOOM-7', g)
    for n in nodes:
        print(n.name, n.path)
asyncio.run(t())
"

# 3. Verify check_drift returns clean result for detector.py
uv run python3 -c "
from loom.core import LoomGraph
from loom.drift.detector import check_drift
import asyncio
async def t():
    g = LoomGraph(graph_name='loom_repo')
    r = await check_drift('src/loom/drift/detector.py', g)
    print(r)
asyncio.run(t())
"

# 4. Verify unimplemented tickets list (any count is fine — just must not crash)
uv run loom trace unimplemented --graph-name loom_repo --limit 10

# 5. Verify MCP server starts clean
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
- [ ] Graph indexed with Jira (`loom_repo`: 1520+ nodes, 4881+ edges, 48 tickets)
- [ ] `loom relink` completed (LOOM_IMPLEMENTS edges present)
- [ ] All 5 verification commands pass
- [ ] Slack mockup screenshot ready (PM asking about LOOM-7)
- [ ] Terminal: font ≥ 16pt, dark theme, 120 cols, notifications off
- [ ] Claude Code `.mcp.json` pointing to `loom_repo`
- [ ] Full dry run completed — every scene runs without error before hitting record
