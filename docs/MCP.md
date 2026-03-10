# Loom MCP Server

Loom provides a Model Context Protocol (MCP) server that exposes code intelligence capabilities to AI agents and editors like Claude Desktop, Windsurf, and other MCP-compatible clients.

## What is MCP?

The Model Context Protocol (MCP) is an open standard that enables AI assistants to securely access external tools and data sources. Loom's MCP server allows agents to query your codebase graph directly.

## Installation

### Prerequisites

1. **Python 3.12+** and **uv** package manager
2. **FalkorDB** running locally or remotely
3. **Indexed repository** (see Quick Start below)

### Install Loom

```bash
pip install loom
```

Or with uv:

```bash
uv pip install loom
```

## Quick Start

### 1. Start FalkorDB

```bash
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

### 2. Index Your Repository

```bash
loom analyze . --graph-name myproject --exclude-tests
```

This creates a graph named `myproject` containing your code structure, call relationships, and embeddings.

### 3. Configure Your MCP Client

#### Windsurf

Add to your Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "loom": {
      "command": "uv",
      "args": ["run", "loom", "serve", "--graph-name", "myproject"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

#### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "loom": {
      "command": "loom",
      "args": ["serve", "--graph-name", "myproject"],
      "env": {
        "LOOM_DB_HOST": "localhost",
        "LOOM_DB_PORT": "6379"
      }
    }
  }
}
```

#### Generic MCP Client

```json
{
  "command": "loom",
  "args": ["serve", "--graph-name", "myproject"],
  "env": {
    "LOOM_DB_HOST": "localhost",
    "LOOM_DB_PORT": "6379"
  }
}
```

## Available Tools

The Loom MCP server exposes 8 tools for code intelligence:

### `search_code`

Search your codebase semantically using embeddings and graph expansion.

**Parameters:**
- `query` (string): Natural language search query
- `limit` (integer, optional): Maximum results (default: 10)

**Example:**
```
Search for "authentication validation logic"
```

**Returns:**
```json
[
  {
    "id": "function:auth/validator.py:validate_user",
    "name": "validate_user",
    "path": "auth/validator.py",
    "score": 0.89
  }
]
```

### `get_callers`

Find all functions that call a specific node.

**Parameters:**
- `node_id` (string): Node ID to find callers for

**Example:**
```
Get callers of "function:auth/hash.py:hash_password"
```

**Returns:**
```json
[
  {
    "id": "function:auth/validator.py:validate_user",
    "name": "validate_user",
    "path": "auth/validator.py",
    "confidence": 0.95
  }
]
```

### `get_spec`

Get specification or documentation linked to a code node.

**Parameters:**
- `node_id` (string): Node ID to find specs for

**Example:**
```
Get spec for "function:auth/validator.py:validate_user"
```

**Returns:**
```json
[
  {
    "id": "doc:specs/auth.md:section-3.2.4",
    "name": "Input Validation",
    "path": "specs/auth.md"
  }
]
```

### `check_drift`

Check for AST drift and semantic violations between code and specifications.

**Parameters:**
- `node_id` (string): Node ID to check drift for

**Example:**
```
Check drift for "function:auth/validator.py:validate_user"
```

**Returns:**
```json
{
  "ast_drift": [
    {
      "node_id": "function:auth/validator.py:validate_user",
      "reasons": ["signature_changed: (username) -> (username, email)", "added_parameters: ['email']"]
    }
  ],
  "semantic_violations": []
}
```

### `get_blast_radius`

Analyze the impact radius - which nodes would be affected if a specific node changes.

**Parameters:**
- `node_id` (string): Node ID to analyze
- `depth` (integer, optional): Traversal depth (default: 3)

**Example:**
```
Get blast radius for "function:core/database.py:connect" with depth 2
```

**Returns:**
```json
[
  {
    "id": "function:api/users.py:get_user",
    "name": "get_user",
    "path": "api/users.py",
    "kind": "function"
  },
  {
    "id": "function:api/posts.py:create_post",
    "name": "create_post",
    "path": "api/posts.py",
    "kind": "function"
  }
]
```

### `get_impact`

Get code nodes impacted by a ticket or requirement.

**Parameters:**
- `ticket_id` (string): Ticket ID (e.g., "PROJ-123")

**Example:**
```
Get impact of ticket "PROJ-456"
```

**Returns:**
```json
[
  {
    "id": "function:auth/validator.py:validate_user",
    "name": "validate_user",
    "path": "auth/validator.py"
  }
]
```

### `get_ticket`

Retrieve ticket details from Jira integration.

**Parameters:**
- `ticket_id` (string): Ticket ID

**Example:**
```
Get ticket "PROJ-123"
```

**Returns:**
```json
[
  {
    "id": "jira://PROJ-123",
    "name": "PROJ-123",
    "summary": "Implement user authentication",
    "path": "jira://your-domain.atlassian.net/browse/PROJ-123",
    "metadata": {"status": "In Progress", "assignee": "alice@example.com"}
  }
]
```

### `unimplemented`

Find tickets that have no implementation links in the codebase.

**Parameters:** None

**Example:**
```
Find unimplemented tickets
```

**Returns:**
```json
[
  {
    "id": "jira://PROJ-789",
    "name": "PROJ-789",
    "path": "jira://your-domain.atlassian.net/browse/PROJ-789"
  }
]
```

## Configuration

Loom uses environment variables for configuration. Set these before starting the MCP server:

### Database Configuration

```bash
LOOM_DB_HOST=localhost          # FalkorDB host
LOOM_DB_PORT=6379               # FalkorDB port
LOOM_DB_PASSWORD=               # Optional password
```

### LLM Configuration (for enrichment)

```bash
LOOM_LLM_MODEL=gpt-4o-mini      # LLM model for summarization
LOOM_LLM_API_KEY=sk-...         # OpenAI API key
LOOM_LLM_BASE_URL=              # Optional custom endpoint
```

### Jira Integration (optional)

```bash
LOOM_JIRA_URL=https://your-domain.atlassian.net
LOOM_JIRA_EMAIL=you@example.com
LOOM_JIRA_API_TOKEN=...
LOOM_JIRA_PROJECT_KEY=PROJ
```

## Advanced Usage

### Multiple Graphs

You can maintain separate graphs for different projects:

```bash
loom analyze ~/project-a --graph-name project-a
loom analyze ~/project-b --graph-name project-b
```

Configure different MCP server instances:

```json
{
  "mcpServers": {
    "loom-project-a": {
      "command": "loom",
      "args": ["serve", "--graph-name", "project-a"]
    },
    "loom-project-b": {
      "command": "loom",
      "args": ["serve", "--graph-name", "project-b"]
    }
  }
}
```

### Incremental Updates

Keep your graph synchronized with code changes:

```bash
# Watch mode (auto-sync on file changes)
loom watch . --graph-name myproject

# Manual sync between git commits
loom sync --old-sha abc123 --new-sha def456 --graph-name myproject --repo-path .
```

### Graph Enrichment

Run expensive enrichment passes for better insights:

```bash
# Add community detection and git coupling analysis
loom enrich --graph-name myproject --coupling-months 6
```

## Troubleshooting

### MCP Server Not Starting

1. **Check FalkorDB is running:**
   ```bash
   docker ps | grep falkordb
   ```

2. **Verify graph exists:**
   ```bash
   loom query "test" --graph-name myproject
   ```

3. **Check logs:** MCP servers log to stderr, visible in your MCP client's logs

### No Results from Tools

1. **Ensure repository is indexed:**
   ```bash
   loom analyze . --graph-name myproject --force
   ```

2. **Check embeddings are generated:**
   ```bash
   loom query "test query" --graph-name myproject
   ```

### Performance Issues

1. **Limit search results:**
   ```
   search_code("query", limit=5)
   ```

2. **Reduce blast radius depth:**
   ```
   get_blast_radius("node_id", depth=2)
   ```

## Examples

### Agent Workflow: Impact Analysis

```
Agent: "What would break if I change the hash_password function?"

1. search_code("hash_password") → get node_id
2. get_blast_radius(node_id, depth=3) → see all dependent code
3. get_spec(node_id) → check if there are requirements
4. check_drift(node_id) → see if already drifted
```

### Agent Workflow: Feature Implementation

```
Agent: "Show me unimplemented features and their impact"

1. unimplemented() → get list of tickets
2. For each ticket:
   - get_ticket(ticket_id) → get details
   - get_impact(ticket_id) → see related code
```

### Agent Workflow: Code Understanding

```
Agent: "How does authentication work?"

1. search_code("authentication") → find relevant nodes
2. For each node:
   - get_callers(node_id) → see usage
   - get_spec(node_id) → read documentation
```

## Best Practices

1. **Index regularly:** Run `loom analyze` after major changes
2. **Use watch mode:** Keep graph synchronized during development
3. **Enrich periodically:** Run `loom enrich` weekly for better insights
4. **Specific queries:** Use precise search terms for better results
5. **Limit results:** Start with small limits and increase if needed

## Resources

- [Main Documentation](../README.md)
- [Architecture Guide](ARCHITECTURE.md)
- [Usage Guide](USAGE.md)
- [GitHub Repository](https://github.com/ddevilz/loom)
- [MCP Specification](https://modelcontextprotocol.io)

## Support

- **Issues:** [GitHub Issues](https://github.com/ddevilz/loom/issues)
- **Security:** See [SECURITY.md](../SECURITY.md)
- **Contributing:** See [CONTRIBUTING.md](../CONTRIBUTING.md)
