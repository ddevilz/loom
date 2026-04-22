# /production-gate

Full production readiness validation for Loom. Tests every CLI command, every MCP tool,
code reproduction fidelity, watch/sync modes, and operational failure scenarios.

This command replaces /smoke-test, /test-mcp, and /phase-gate.
Run it when you believe Loom is ready for real users.

Work autonomously through all sections. Never skip a section.
Record every result. Output the final verdict table at the end.
Stop only on total FalkorDB failure. Flag everything else and continue.

---

## Pre-flight — environment check

```bash
# 1. Package installs correctly
uv run loom --dev && echo "IMPORT OK" || echo "IMPORT FAILED"

# 2. Version present
uv run loom --version

# 3. FalkorDB reachable
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('_preflight_check')
r = g.query('RETURN 1 AS ok')
print('DB:', 'OK' if r.result_set else 'FAILED')
"

# 4. Jira reachable (non-fatal if fails — Jira is optional)
curl -s -o /dev/null -w "Jira HTTP: %{http_code}\n" \
  -u jadhavom263@gmail.com:$LOOM_JIRA_API_TOKEN \
  "https://devaloom.atlassian.net/rest/api/3/project/LOOM"
```

If FalkorDB fails → STOP. Fix docker/connection before continuing.
If Jira returns non-200 → flag, skip Jira-dependent checks, continue everything else.

---

## SECTION 1 — Core indexing: `loom analyze`

### 1.1 — Force index (baseline)

```bash
uv run loom analyze . --graph-name loom_repo --force 2>&1 | tee /tmp/loom-analyze.log
echo "Exit code: $?"
grep -iE "error|exception|traceback" /tmp/loom-analyze.log | grep -v "# " | head -10
grep -iE "indexed|files|nodes|edges|created|skipped" /tmp/loom-analyze.log | tail -15
```

Record: files indexed, nodes created, edges created, exit code, runtime.

**Pass:**
- [ ] Exit code 0
- [ ] Prints file count, node count, edge count (not "0" for any)
- [ ] No unhandled exceptions
- [ ] Runtime < 5 min

### 1.2 — Incremental re-index (second run without --force)

```bash
time uv run loom analyze . --graph-name loom_repo 2>&1 | tee /tmp/loom-incremental.log
echo "Exit: $?"
grep -iE "skipped|unchanged|cached|incremental" /tmp/loom-incremental.log | head -10
```

**Pass:**
- [ ] Faster than force run
- [ ] Reports files skipped/unchanged (not re-processing everything)
- [ ] Node/edge counts match force run (graph state identical)
- [ ] No "hash miss silently reusing stale" behavior

### 1.3 — Exclude tests flag

```bash
uv run loom analyze . --graph-name loom_repo --force --exclude-tests 2>&1 | tee /tmp/loom-notests.log
# Count test files in result
grep -i "test_\|_test\." /tmp/loom-notests.log | head -5
```

**Pass:**
- [ ] No `test_*.py` files appear in indexed output
- [ ] Node count lower than full index (tests excluded)

### 1.4 — Force-index with Jira (skip if Jira unreachable)

```bash
LOOM_JIRA_API_TOKEN="<your-atlassian-api-token>"
uv run loom analyze . --graph-name loom_repo --force \
  --jira-project LOOM \
  --jira-url https://devaloom.atlassian.net \
  --jira-email jadhavom263@gmail.com \
  --jira-token $LOOM_JIRA_API_TOKEN 2>&1 | tee /tmp/loom-jira.log
grep -iE "jira|ticket|linked|401|404|error" /tmp/loom-jira.log | head -15
```

**Pass:**
- [ ] Jira auth validated before indexing starts
- [ ] At least 1 Jira ticket linked (not 0)
- [ ] No raw stack trace on auth failure — clean error message
- [ ] `--jira-project LOOM` validated before long run starts

### 1.5 — Bad input handling

```bash
uv run loom analyze /nonexistent/path --graph-name test 2>&1 | head -5
echo "Exit: $?"
uv run loom analyze . --graph-name "" 2>&1 | head -5
echo "Exit: $?"
```

**Pass:**
- [ ] Clear error messages — not raw Python tracebacks
- [ ] Non-zero exit codes on both

---

## SECTION 2 — Query & trace commands

### 2.1 — `loom query`

```bash
# Semantic search via CLI
uv run loom query "how does authentication work" --graph-name loom_repo --limit 5 2>&1
uv run loom query "how is the graph indexed incrementally" --graph-name loom_repo 2>&1
```

**Pass:**
- [ ] Returns results with symbol name and file path
- [ ] Results are semantically relevant (not random noise)
- [ ] Scores are numeric and > 0
- [ ] `--limit` flag is respected

### 2.2 — `loom trace` (all modes)

```bash
# Untraced: functions with no doc/ticket links
uv run loom trace untraced --graph-name loom_repo 2>&1 | head -30

# Coverage: overall traceability stats
uv run loom trace coverage --graph-name loom_repo 2>&1 | head -20

# Impact: code affected by a specific Jira ticket (skip if no Jira)
uv run loom trace impact LOOM-1 --graph-name loom_repo 2>&1 | head -20

# Tickets: traceability from ticket side
uv run loom trace tickets --graph-name loom_repo 2>&1 | head -20

# Unimplemented: tickets with no code links
uv run loom trace unimplemented --graph-name loom_repo 2>&1 | head -20
```

**Pass for each mode:**
- [ ] Returns structured output (not empty, not crash)
- [ ] `untraced` lists real function names with file paths
- [ ] `coverage` returns a percentage or count breakdown
- [ ] `impact LOOM-1` returns affected files/functions (or "no code links found" — explicit, not silent)
- [ ] `unimplemented` returns tickets with no linked code, not an empty list when tickets exist

### 2.3 — `loom calls`

```bash
# Callers of a specific node
uv run loom calls --target SemanticLinker --direction both --graph-name loom_repo 2>&1

# Callers only
uv run loom calls --target link --direction callers --graph-name loom_repo 2>&1

# Callees only
uv run loom calls --target link --direction callees --graph-name loom_repo 2>&1
```

**Pass:**
- [ ] `--direction callers` returns who calls the target (not what target calls)
- [ ] `--direction callees` returns what the target calls (not who calls it)
- [ ] `--direction both` returns both sets clearly labeled
- [ ] Results include file paths, not just symbol names
- [ ] Returns "not found" cleanly if symbol doesn't exist

### 2.4 — `loom blast_radius`

```bash
uv run loom blast_radius --node validate_user --graph-name loom_repo --depth 3 2>&1
uv run loom blast_radius --node SemanticLinker --graph-name loom_repo --depth 2 2>&1
```

**Pass:**
- [ ] Output matches the tree format in README:
      `symbol (file.py) ← CALLS` with depth indentation
- [ ] Callers, not callees (verify: first result calls the target)
- [ ] Includes `docs_at_risk` section when IMPLEMENTS edges exist
- [ ] `--depth` flag respected (no results deeper than specified)
- [ ] Returns structured result even if 0 callers (not crash)

### 2.5 — `loom entrypoints`

```bash
uv run loom entrypoints --graph-name loom_repo --limit 15 2>&1
```

**Pass:**
- [ ] Returns symbols with no incoming CALLS edges (true entry points)
- [ ] Includes call counts and relationship counts
- [ ] CLI entry points (main/serve/analyze) are in the list

### 2.6 — `loom tickets`

```bash
# All tickets
uv run loom tickets --graph-name loom_repo --limit 20 2>&1

# Connected only (tickets linked to code)
uv run loom tickets --connected --graph-name loom_repo --limit 20 2>&1
```

**Pass:**
- [ ] Returns Jira tickets stored in graph with key, summary, status
- [ ] `--connected` filters to only tickets that have code links
- [ ] Non-connected tickets excluded from `--connected` output

---

## SECTION 3 — Enrichment commands

### 3.1 — `loom enrich`

```bash
uv run loom enrich --graph-name loom_repo 2>&1 | tee /tmp/loom-enrich.log
echo "Exit: $?"
grep -iE "community|coupling|enriched|error" /tmp/loom-enrich.log | head -20
```

**Pass:**
- [ ] Exit code 0
- [ ] Community nodes created (MEMBER_OF edges exist after)
- [ ] COUPLED_WITH edges created
- [ ] Runtime acceptable (warn if > 10 min)

```bash
# Verify enrichment produced graph artifacts
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('MATCH ()-[r:MEMBER_OF]->() RETURN count(r) AS cnt')
print('MEMBER_OF edges:', r.result_set[0][0])
r2 = g.query('MATCH ()-[r:COUPLED_WITH]->() RETURN count(r) AS cnt')
print('COUPLED_WITH edges:', r2.result_set[0][0])
"
```

**Pass:**
- [ ] MEMBER_OF count > 0
- [ ] COUPLED_WITH count > 0

### 3.2 — `loom relink`

```bash
uv run loom relink --graph-name loom_repo 2>&1 | tee /tmp/loom-relink.log
echo "Exit: $?"
grep -iE "linked|implements|specifies|threshold|error" /tmp/loom-relink.log | head -20

# Verify LOOM_IMPLEMENTS edges updated
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('MATCH ()-[r:LOOM_IMPLEMENTS]->() RETURN count(r) AS cnt')
print('LOOM_IMPLEMENTS edges after relink:', r.result_set[0][0])
"
```

**Pass:**
- [ ] Exit code 0
- [ ] Reports number of edges created/updated
- [ ] LOOM_IMPLEMENTS count >= count before relink (never reduces)
- [ ] `--embedding-threshold` flag accepted without error

---

## SECTION 4 — Watch and sync modes

### 4.1 — `loom watch` basic stability

```bash
# Start watcher in background
uv run loom watch . --graph-name loom_repo --debounce 200 2>/tmp/loom-watch.log &
WATCH_PID=$!
sleep 3

# Simulate a file change
echo "# watch test $(date)" >> src/loom/config.py
sleep 2

# Check log for update signal
grep -iE "changed|updated|indexed|error" /tmp/loom-watch.log | head -10

# Clean up
git checkout src/loom/config.py 2>/dev/null || sed -i '$ d' src/loom/config.py
kill $WATCH_PID 2>/dev/null
echo "Watch PID stopped"
```

**Pass:**
- [ ] Watcher starts without crash
- [ ] File change is detected and logged within debounce window
- [ ] Graph updated (node hash changes)
- [ ] Watcher continues running after change (does not crash on update)
- [ ] File deletion is handled: delete a file, check orphan nodes cleaned up

### 4.2 — `loom sync`

```bash
# Get last two commits
OLD_SHA=$(git log --format="%H" | sed -n '2p')
NEW_SHA=$(git log --format="%H" | head -1)
echo "Syncing $OLD_SHA → $NEW_SHA"

uv run loom sync --old-sha $OLD_SHA --new-sha $NEW_SHA \
  --graph-name loom_repo --repo-path . 2>&1 | tee /tmp/loom-sync.log
echo "Exit: $?"
grep -iE "added|removed|modified|synced|error" /tmp/loom-sync.log | head -20
```

**Pass:**
- [ ] Exit code 0
- [ ] Reports files added/removed/modified between SHAs
- [ ] Graph reflects only changes between SHAs (not full re-index)
- [ ] Same node count as after analyze (sync is idempotent with no real changes)

---

## SECTION 5 — MCP server and all tools

Start the server once for all tool tests.

```bash
uv run loom serve --graph-name loom_repo 2>/tmp/loom-mcp-err.log &
MCP_PID=$!
sleep 2
cat /tmp/loom-mcp-err.log
echo "MCP PID: $MCP_PID"
```

Helper function for all calls:
```bash
mcp() {
  echo "{\"jsonrpc\":\"2.0\",\"id\":$1,\"method\":\"tools/call\",\"params\":{\"name\":\"$2\",\"arguments\":$3}}" \
    | uv run loom serve --graph-name loom_repo 2>/dev/null \
    | python -c "import json,sys; d=json.load(sys.stdin); c=d.get('result',{}).get('content',[{}])[0].get('text','{}'); print(c[:500])"
}
```

### 5.1 — `tools/list` — all tools registered

```bash
echo '{"jsonrpc":"2.0","id":0,"method":"tools/list","params":{}}' \
  | uv run loom serve --graph-name loom_repo 2>/dev/null \
  | python -c "
import json,sys
d=json.load(sys.stdin)
tools=d.get('result',{}).get('tools',[])
expected={'search_code','get_callers','get_spec','check_drift','get_blast_radius','get_impact','get_ticket','unimplemented','relink'}
found={t['name'] for t in tools}
print(f'Found {len(found)} tools: {sorted(found)}')
missing=expected-found
if missing: print(f'MISSING: {missing}')
for t in tools:
    desc=t.get('description','')
    if not desc or len(desc)<10: print(f'  WARN: {t[\"name\"]} has weak description: {repr(desc)}')
"
```

**Pass:**
- [ ] All 9 expected tools present
- [ ] Every tool has a description > 10 chars (not placeholder)
- [ ] Input schema defined for each tool

### 5.2 — `search_code` (was `semantic_search`)

```bash
mcp 1 "search_code" '{"query":"how does the semantic linker create edges","limit":5}'
mcp 2 "search_code" '{"query":"unrelated nonsense about cooking recipes","limit":3}'
```

**Pass:**
- [ ] Query 1: returns results with name, file, score fields
- [ ] Query 1: top result is linker-related (linker.py or embed_match.py)
- [ ] Query 2: scores < 0.5 or empty — no false high-confidence results
- [ ] Response time < 5s

### 5.3 — `get_callers`

```bash
mcp 3 "get_callers" '{"node":"link"}'
mcp 4 "get_callers" '{"node":"SemanticLinker"}'
```

**Pass:**
- [ ] Returns list of symbols that call the target (incoming CALLS, one hop)
- [ ] Each result has name, file, edge_label
- [ ] Does NOT return callees (what link() calls)
- [ ] Empty list with clear message if no callers — not crash

### 5.4 — `get_spec`

```bash
mcp 5 "get_spec" '{"node":"SemanticLinker"}'
mcp 6 "get_spec" '{"node":"blast_radius"}'
```

**Pass:**
- [ ] Returns Jira tickets linked via LOOM_IMPLEMENTS edges
- [ ] Each result has ticket key, summary, status
- [ ] Empty list (not error) if no linked tickets

### 5.5 — `check_drift`

```bash
# No drift on unmodified file
mcp 7 "check_drift" '{"file_path":"src/loom/linker/linker.py"}'

# Introduce drift, re-check
echo "# drift test" >> src/loom/linker/linker.py
mcp 8 "check_drift" '{"file_path":"src/loom/linker/linker.py"}'
git checkout src/loom/linker/linker.py 2>/dev/null || sed -i '$ d' src/loom/linker/linker.py
```

**Pass:**
- [ ] Unmodified: `drifted: false`
- [ ] Modified: `drifted: true`
- [ ] Response does NOT contain `semantic_violations` key (BUG-4 regression)
- [ ] Response includes file and hash fields

### 5.6 — `get_blast_radius`

```bash
mcp 9 "get_blast_radius" '{"node":"SemanticLinker","depth":3}'
```

**Pass:**
- [ ] Returns `root`, `summary` (total_nodes, hops), `callers`, `docs_at_risk`, `warnings`
- [ ] Callers are symbols that call SemanticLinker — not what it calls
- [ ] `docs_at_risk` includes docs linked via LOOM_IMPLEMENTS if any exist
- [ ] `depth` respected — no callers at depth > 3

### 5.7 — `get_impact`

```bash
mcp 10 "get_impact" '{"ticket":"LOOM-1"}'
```

**Pass:**
- [ ] Returns code nodes linked to the ticket (inverse of get_spec)
- [ ] Each result has symbol name, file path
- [ ] Empty list (not error) if ticket has no code links

### 5.8 — `get_ticket`

```bash
mcp 11 "get_ticket" '{"ticket_key":"LOOM-1"}'
mcp 12 "get_ticket" '{"ticket_key":"DOES-NOT-EXIST"}'
```

**Pass:**
- [ ] LOOM-1: returns raw ticket data (key, summary, status, description)
- [ ] Non-existent key: returns "not found" message — not crash, not empty dict

### 5.9 — `unimplemented`

```bash
mcp 13 "unimplemented" '{}'
```

**Pass:**
- [ ] Returns tickets with no linked code nodes
- [ ] Each result has ticket key and summary
- [ ] Does not return tickets that DO have code links

### 5.10 — `relink`

```bash
mcp 14 "relink" '{}'
```

**Pass:**
- [ ] Executes the semantic linker without re-indexing files
- [ ] Returns count of edges created/updated
- [ ] Does not crash or timeout (warn if > 60s)

```bash
# Shut down MCP server
kill $MCP_PID 2>/dev/null
echo "MCP stopped"
```

---

## SECTION 6 — Code reproduction fidelity

### 6.1 — Symbol completeness

```bash
# Count actual functions and classes in source
ACTUAL=$(grep -rn "^def \|^class \|^    def " src/loom/ --include="*.py" | wc -l)
echo "Source symbols: $ACTUAL"

uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('MATCH (s:Symbol) RETURN count(s) AS cnt')
graph_count = r.result_set[0][0]
print(f'Graph symbols: {graph_count}')
ratio = graph_count / $ACTUAL
print(f'Coverage ratio: {ratio:.0%}')
if ratio < 0.5: print('FAIL: < 50% of symbols indexed')
elif ratio < 0.8: print('WARN: < 80% of symbols indexed')
else: print('PASS')
"
```

### 6.2 — CALLS edge direction verification

```bash
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')

# Pick 3 functions we know call others
targets = ['link', 'embed', 'ingest_repository']
for fn in targets:
    r = g.query(f'''
      MATCH (caller:Symbol)-[:CALLS]->(target:Symbol)
      WHERE target.name CONTAINS \"{fn}\"
      RETURN caller.name, caller.file, target.name
      LIMIT 3
    ''')
    print(f'\\nCallers of {fn}: {len(r.result_set)} found')
    for row in r.result_set:
        print(f'  {row[0]} ({row[1]}) → calls → {row[2]}')
    if not r.result_set:
        print(f'  WARN: no CALLS edges for {fn}')
"
```

For each result: open the actual source file and confirm the caller genuinely calls the target.

### 6.3 — Cross-file CALLS edges

```bash
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('''
  MATCH (a:Symbol)-[:CALLS]->(b:Symbol)
  WHERE a.file <> b.file
  RETURN a.file, b.file, count(*) AS cnt
  ORDER BY cnt DESC LIMIT 10
''')
print(f'Cross-file CALLS edges: {len(r.result_set)} file pairs')
for row in r.result_set:
    print(f'  {row[0]} → {row[1]}: {row[2]} calls')
if not r.result_set:
    print('FAIL: no cross-file call edges — blast_radius is useless without these')
"
```

### 6.4 — Multi-language call tracing

```bash
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')

langs = {
    'py': 'Python',
    'ts': 'TypeScript',
    'tsx': 'TSX',
    'js': 'JavaScript',
    'jsx': 'JSX',
}
for ext, name in langs.items():
    r = g.query(f'''
      MATCH (a:Symbol)-[:CALLS]->(b:Symbol)
      WHERE a.file ENDS WITH '.{ext}'
      RETURN count(*) AS cnt
    ''')
    cnt = r.result_set[0][0]
    status = 'OK' if cnt > 0 else 'ZERO (no call edges for this language)'
    print(f'  {name} ({ext}): {cnt} CALLS edges — {status}')
"
```

**Pass:**
- [ ] Python: > 0 CALLS edges
- [ ] TypeScript + JSX/JS: > 0 CALLS edges (BUG-1 regression check)
- [ ] Any language with 0 CALLS edges is flagged

### 6.5 — Edge type completeness

```bash
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('MATCH ()-[e]->() RETURN type(e) AS t, count(e) AS cnt ORDER BY cnt DESC')
print('All edge types:')
found = set()
for row in r.result_set:
    found.add(row[0])
    print(f'  {row[0]}: {row[1]}')

required = {'CALLS', 'LOOM_IMPLEMENTS', 'LOOM_SPECIFIES', 'MEMBER_OF', 'COUPLED_WITH'}
missing = required - found
if missing:
    print(f'MISSING edge types: {missing}')
else:
    print('All required edge types present')
"
```

### 6.6 — Orphan node check

```bash
uv run python -c "
from src.loom.core.falkor.gateway import FalkorGateway
g = FalkorGateway(); g.connect('loom_repo')
r = g.query('MATCH (n) WHERE NOT (n)--() RETURN labels(n)[0] AS label, n.name LIMIT 20')
print(f'Orphaned nodes: {len(r.result_set)}')
for row in r.result_set[:10]:
    print(f'  [{row[0]}] {row[1]}')
total = g.query('MATCH (n) RETURN count(n) AS cnt').result_set[0][0]
ratio = len(r.result_set) / max(total, 1)
if ratio > 0.05:
    print(f'FAIL: {ratio:.0%} of nodes orphaned (> 5% threshold)')
"
```

---

## SECTION 7 — Operational / production scenarios

### 7.1 — Concurrent indexing (two runs at once)

```bash
# Start two analyze runs simultaneously
uv run loom analyze . --graph-name loom_repo_a --force > /tmp/loom-concurrent-a.log 2>&1 &
PID_A=$!
uv run loom analyze . --graph-name loom_repo_b --force > /tmp/loom-concurrent-b.log 2>&1 &
PID_B=$!
wait $PID_A; echo "A exit: $?"
wait $PID_B; echo "B exit: $?"
grep -i "error\|lock\|conflict" /tmp/loom-concurrent-a.log /tmp/loom-concurrent-b.log | head -10
```

**Pass:**
- [ ] Both exit 0 (or one exits with a clear "graph locked" message — not crash)
- [ ] Node counts in both resulting graphs are correct
- [ ] No DB corruption (run a query against each after)

### 7.2 — FalkorDB restart recovery

```bash
# Kill DB, try a query, restart DB, try again
docker stop loom-db 2>/dev/null || true
sleep 1
uv run loom query "test" --graph-name loom_repo 2>&1 | head -5
# Expected: clear error "DB unreachable", not hang

docker start loom-db 2>/dev/null || docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
sleep 3
uv run loom query "how does the linker work" --graph-name loom_repo 2>&1 | head -10
# Expected: works again after restart
```

**Pass:**
- [ ] DB down: produces a clear error within 5 seconds — no hang
- [ ] DB restart: queries work again without restarting loom

### 7.3 — Watch mode edge cases

```bash
uv run loom watch . --graph-name loom_repo --debounce 200 2>/tmp/loom-watch-edge.log &
WATCH_PID=$!
sleep 2

# Rapid saves (5 in 1 second — should debounce to 1 update)
for i in 1 2 3 4 5; do
  echo "# save $i" >> src/loom/config.py && sleep 0.2
done
sleep 2
grep -c "indexed\|updated" /tmp/loom-watch-edge.log
# Expected: 1-2 updates, not 5 (debouncing works)

# File deletion
rm /tmp/loom_test_delete.py 2>/dev/null
echo "def orphan_func(): pass" > /tmp/loom_test_delete.py
cp /tmp/loom_test_delete.py src/loom/loom_test_delete.py
sleep 2
rm src/loom/loom_test_delete.py
sleep 2
grep -i "delete\|removed" /tmp/loom-watch-edge.log | head -5

git checkout src/loom/config.py 2>/dev/null || sed -i '$ d' src/loom/config.py
kill $WATCH_PID 2>/dev/null
```

**Pass:**
- [ ] 5 rapid saves = 1-2 graph updates (debounce working)
- [ ] Deleted file triggers node removal in graph
- [ ] Watcher never crashes during the test

### 7.4 — MCP large query (no hang, bounded results)

```bash
# Unbounded query should be limited, not hang
echo '{"jsonrpc":"2.0","id":99,"method":"tools/call","params":{"name":"search_code","arguments":{"query":"function","limit":1000}}}' \
  | timeout 10 uv run loom serve --graph-name loom_repo 2>/dev/null \
  | python -c "
import json,sys
d=json.load(sys.stdin)
content=d.get('result',{}).get('content',[{}])[0].get('text','[]')
results=json.loads(content) if isinstance(content,str) else []
print(f'Results returned for limit=1000: {len(results) if isinstance(results,list) else \"non-list\"}')
print('Completed within timeout: YES')
" 2>/dev/null || echo "TIMEOUT or CRASH"
```

**Pass:**
- [ ] Completes within 10 seconds
- [ ] Returns bounded results (not all nodes in the graph)

---

## SECTION 8 — Final verdict

Print this table after all sections:

```
## Production Gate Report — Loom

### CLI Commands
| Command | Tested | Pass | Notes |
|---|---|---|---|
| loom analyze (force) | ✅ | ✅/❌ | |
| loom analyze (incremental) | ✅ | ✅/❌ | |
| loom analyze --exclude-tests | ✅ | ✅/❌ | |
| loom analyze + Jira | ✅ | ✅/❌/⚠️ skipped | |
| loom query | ✅ | ✅/❌ | |
| loom trace untraced | ✅ | ✅/❌ | |
| loom trace coverage | ✅ | ✅/❌ | |
| loom trace impact | ✅ | ✅/❌ | |
| loom trace unimplemented | ✅ | ✅/❌ | |
| loom calls (callers) | ✅ | ✅/❌ | |
| loom calls (callees) | ✅ | ✅/❌ | |
| loom blast_radius | ✅ | ✅/❌ | |
| loom entrypoints | ✅ | ✅/❌ | |
| loom tickets | ✅ | ✅/❌ | |
| loom enrich | ✅ | ✅/❌ | |
| loom relink | ✅ | ✅/❌ | |
| loom watch | ✅ | ✅/❌ | |
| loom sync | ✅ | ✅/❌ | |

### MCP Tools (9 total)
| Tool | Responds | Output Correct | Quality |
|---|---|---|---|
| search_code | ✅/❌ | ✅/❌ | Relevant/Noisy |
| get_callers | ✅/❌ | ✅/❌ | Correct direction/Wrong |
| get_spec | ✅/❌ | ✅/❌ | Has tickets/Empty |
| check_drift | ✅/❌ | ✅/❌ | Detects/Always false |
| get_blast_radius | ✅/❌ | ✅/❌ | Correct shape/Missing fields |
| get_impact | ✅/❌ | ✅/❌ | |
| get_ticket | ✅/❌ | ✅/❌ | |
| unimplemented | ✅/❌ | ✅/❌ | |
| relink | ✅/❌ | ✅/❌ | |

### Code Reproduction
| Check | Result |
|---|---|
| Symbol coverage (>80% of source) | X% |
| CALLS direction correct | ✅/❌ |
| Cross-file CALLS edges exist | X edges |
| JS/JSX/TS call tracing (BUG-1) | ✅/❌ |
| All edge types present | ✅/❌ — missing: X |
| Orphaned nodes < 5% | X% |

### Bug Regressions
| Bug | Status |
|---|---|
| BUG-1: JS/JSX call_tracer | ✅/❌ |
| BUG-2: serve flags accurate | ✅/❌ |
| BUG-3: igraph lazy import | ✅/❌ |
| BUG-4: no semantic_violations | ✅/❌ |

### Operational
| Scenario | Result |
|---|---|
| Concurrent indexing | ✅ Both clean / ❌ Crash/corruption |
| DB restart recovery | ✅ Recovers / ❌ Hangs |
| Watch debounce | ✅ 1-2 updates / ❌ 5 updates |
| Watch file deletion | ✅ Node removed / ❌ Orphan left |
| MCP large query bounded | ✅ / ❌ Timeout |

### Blockers (must fix before production)
1. <item>

### Deferred (can ship with known limitation)
1. <item>

### PRODUCTION READY: YES / NO
```

**PRODUCTION READY = YES** requires:
- All 18 CLI commands pass
- All 9 MCP tools respond with correct output
- Symbol coverage > 80%
- Cross-file CALLS edges > 0
- JS/JSX CALLS edges > 0
- All 4 bug regressions clean
- No concurrent indexing crash or DB corruption
- DB restart recovery works