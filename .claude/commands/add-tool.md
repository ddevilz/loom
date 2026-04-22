Add a new MCP tool to Loom's FastMCP server. Follow the conventions below exactly.

## Context
- MCP server: `mcp/server.py`
- Transport: stdio (FastMCP)
- All tools are registered with `@mcp.tool`
- Input validation via Pydantic v2
- All graph queries go through FalkorDB via the shared client

## Tool spec
Describe the tool you want to add:
- **Name**: (snake_case, verb-first e.g. `query_callers`, `explain_edge`)
- **Purpose**: one sentence
- **Inputs**: field names, types, descriptions
- **Output**: what the tool returns (structure + example)
- **Edge types it reads/writes**: e.g. CALLS, IMPLEMENTS, SPECIFIES, VIOLATES

## Implementation checklist
When implementing the tool, Claude must:

1. Define a Pydantic `BaseModel` for inputs in `mcp/server.py`.
2. Register with `@mcp.tool` — include a docstring that will become the tool description visible to LLMs. Make it accurate and agent-friendly.
3. Add annotations:
   - `readOnlyHint: true` if the tool only reads from FalkorDB
   - `destructiveHint: true` if it mutates graph state
4. Use explicit error raises — never return `{"error": None}` or swallow exceptions silently.
5. Add a corresponding test in `tests/test_mcp_tools.py`.
6. Update the **MCP Tools** table in `CLAUDE.md`.

## Output
Show the complete implementation diff, then run:
```bash
mypy mcp/server.py && pytest tests/test_mcp_tools.py -v -k <new_tool_name>
```
