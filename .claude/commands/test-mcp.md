# /test-mcp

Manual end-to-end test of the Loom MCP server. Runs the server and exercises every tool via CLI.
Use after unit tests pass to verify the real server behavior — not mocks.

---

## Step 1 — Index a test repo first (if not already done)

Pick a small repo with JS/JSX and Python files (both, to exercise BUG-1 fix):

```bash
# Use the Loom repo itself as the test target (dogfooding)
loom index . --output /tmp/loom-test-graph

# Or a small fixture repo if you have one
loom index ./tests/fixtures/sample-repo --output /tmp/loom-test-graph
```

Expected: no errors, summary of nodes and edges indexed printed to stdout.
If JS/JSX files are present, you should see CALLS edges for them (confirms BUG-1 fix).

---

## Step 2 — Start the MCP server

```bash
# Start in background, log to file so you can inspect it
loom serve 2>&1 | tee /tmp/loom-server.log &
LOOM_PID=$!
echo "Server PID: $LOOM_PID"
```

Check the log immediately:
```bash
tail -5 /tmp/loom-server.log
```

**BUG-2 check:** If `--host` and `--port` are in the CLI, confirm the log shows the actual
host/port being used (not just printed and ignored). If stdio-only, confirm no host/port confusion.

---

## Step 3 — Exercise each MCP tool via MCP Inspector or direct stdin

### Option A — MCP Inspector (recommended)
```bash
npx @modelcontextprotocol/inspector loom serve
```
This opens a browser UI where you can call each tool manually.

### Option B — Direct stdin (stdio transport)

Send JSON-RPC messages directly. One at a time:

```bash
# List available tools
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | loom serve

# Call semantic_search
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"semantic_search","arguments":{"query":"what calls the semantic linker","top_k":3}}}' | loom serve

# Call blast_radius (use a real symbol from your indexed repo)
echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"blast_radius","arguments":{"symbol":"loom.linker.SemanticLinker.link","depth":3}}}' | loom serve

# Call check_drift on a specific file
echo '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"check_drift","arguments":{"file_path":"loom/repositories.py"}}}' | loom serve

# Call explain_symbol
echo '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"explain_symbol","arguments":{"symbol":"loom.repositories._rank_by_personalized_pagerank"}}}' | loom serve
```

---

## Step 4 — Assertions to verify manually

After each tool call, check:

**semantic_search** → returns results with `symbol`, `score`, `doc` fields. Score > 0.
**blast_radius** → returns callers (incoming edges), NOT callees. Verify direction is correct.
**check_drift** → response does NOT contain `semantic_violations` key (BUG-4 fix verified).
**explain_symbol** → returns edge list with types: `IMPLEMENTS`, `SPECIFIES`, `VIOLATES`, or `CALLS`.
**tools/list** → all expected tools present, descriptions are non-empty and accurate.

---

## Step 5 — Cleanup

```bash
kill $LOOM_PID 2>/dev/null
echo "Server stopped"
```

---

## Failure protocol

If any tool call returns an error or unexpected shape:
1. Note the exact request + response
2. Run `/fix-and-test` targeting that specific tool
3. Do NOT restart the server and hope — diagnose the root cause first

---

## Quick re-run (after fixes)

```bash
# Re-index, re-serve, re-test in one shot
loom index . --output /tmp/loom-test-graph && \
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | loom serve
```
