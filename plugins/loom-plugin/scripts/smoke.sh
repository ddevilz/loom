#!/usr/bin/env bash
# Loom Plugin Contract Smoke Test
# Verifies all 10 contract checks defined in ADR-0001.
# Usage: bash plugins/loom-plugin/scripts/smoke.sh
# Expected: 10 passed, 0 failed

set -uo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASSED=0
FAILED=0
SKIPPED=0

pass() { echo "  PASS: $1"; ((PASSED++)); }
fail() { echo "  FAIL: $1"; ((FAILED++)); }
skip() { echo "  SKIP: $1"; ((SKIPPED++)); }

echo "=== Loom Plugin Smoke Test ==="
echo "Plugin dir: $PLUGIN_DIR"
echo ""

# 1. plugin.json declares version 0.5.0 with required keywords
echo "[1] plugin.json version + keywords"
MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"
if [ ! -f "$MANIFEST" ]; then
  fail "plugin.json not found"
else
  VERSION=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(d.get('version',''))" 2>/dev/null)
  KEYWORDS=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(' '.join(d.get('keywords',[])))" 2>/dev/null)
  if [[ "$VERSION" == "0.5.0" ]]; then pass "version is 0.5.0"; else fail "version is '$VERSION', expected 0.5.0"; fi
  if echo "$KEYWORDS" | grep -q "loom"; then pass "keyword 'loom' present"; else fail "keyword 'loom' missing"; fi
fi

# 2. mcpServers.loom uses uvx --from loom-tool loom-mcp
echo "[2] mcpServers.loom uses uvx --from loom-tool loom-mcp"
CMD=$(python3 -c "import json; d=json.load(open('$MANIFEST')); s=d.get('mcpServers',{}).get('loom',{}); print(s.get('command',''), ' '.join(s.get('args',[])))" 2>/dev/null)
if echo "$CMD" | grep -q "uvx" && echo "$CMD" | grep -q "loom-tool" && echo "$CMD" | grep -q "loom-mcp"; then
  pass "MCP server uses uvx --from loom-tool loom-mcp"
else
  fail "MCP server command unexpected: '$CMD'"
fi

# 3. All 3 agents present with valid YAML frontmatter
echo "[3] Agents (navigator, summarizer, analyst)"
AGENTS_DIR="$PLUGIN_DIR/agents"
for agent in navigator summarizer analyst; do
  AGENT_FILE="$AGENTS_DIR/$agent.md"
  if [ ! -f "$AGENT_FILE" ]; then
    fail "agent $agent.md not found"
  else
    if grep -q "^name:" "$AGENT_FILE" && grep -q "^description:" "$AGENT_FILE"; then
      pass "agent $agent has valid frontmatter"
    else
      fail "agent $agent missing name/description in frontmatter"
    fi
  fi
done

# 4. All 4 skills present with allowed-tools defined
echo "[4] Skills (onboard, explore-code, impact-analysis, document-code)"
SKILLS_DIR="$PLUGIN_DIR/skills"
for skill in onboard explore-code impact-analysis document-code; do
  SKILL_FILE="$SKILLS_DIR/$skill/SKILL.md"
  if [ ! -f "$SKILL_FILE" ]; then
    fail "skill $skill/SKILL.md not found"
  else
    if grep -q "^allowed-tools:" "$SKILL_FILE"; then
      pass "skill $skill has allowed-tools"
    else
      fail "skill $skill missing allowed-tools"
    fi
  fi
done

# 5. No skill grants wildcard tool access
echo "[5] No wildcard tool access in skills"
WILDCARD_FOUND=0
for skill_file in "$SKILLS_DIR"/*/SKILL.md; do
  if grep -q '"\*"' "$skill_file" || grep -q "^  - \*$" "$skill_file"; then
    fail "wildcard tool access found in $skill_file"
    WILDCARD_FOUND=1
  fi
done
if [ "$WILDCARD_FOUND" -eq 0 ]; then
  pass "no wildcard tool access in any skill"
fi

# 6. All 7 commands present
echo "[6] Commands (loom-analyze, loom-context, loom-summaries, loom-blast, loom-delta, loom-topology, loom-savings)"
COMMANDS_DIR="$PLUGIN_DIR/commands"
for cmd in loom-analyze loom-context loom-summaries loom-blast loom-delta loom-topology loom-savings; do
  CMD_FILE="$COMMANDS_DIR/$cmd.md"
  if [ ! -f "$CMD_FILE" ]; then
    fail "command $cmd.md not found"
  else
    pass "command $cmd present"
  fi
done

# 7. ADR-0001 exists with status "Accepted"
echo "[7] ADR-0001 exists with status Accepted"
ADR_FILE="$PLUGIN_DIR/docs/adrs/0001-loom-plugin-contract.md"
if [ ! -f "$ADR_FILE" ]; then
  fail "ADR-0001 not found"
else
  if grep -q "Status.*Accepted" "$ADR_FILE" || grep -q "\*\*Status:\*\* Accepted" "$ADR_FILE"; then
    pass "ADR-0001 present with status Accepted"
  else
    fail "ADR-0001 found but status is not 'Accepted'"
  fi
fi

# 8. README exists and documents install + quick-start
echo "[8] README documents install and quick-start"
README="$PLUGIN_DIR/README.md"
if [ ! -f "$README" ]; then
  fail "README.md not found"
else
  if grep -qi "install" "$README" && grep -qi "loom analyze" "$README"; then
    pass "README documents install and loom analyze"
  else
    fail "README missing install or quick-start documentation"
  fi
fi

# 9. loom://primer and loom://savings resources documented
echo "[9] MCP resources (loom://primer, loom://savings) documented in README"
if grep -q "loom://primer" "$README" && grep -q "loom://savings" "$README"; then
  pass "MCP resources documented in README"
else
  fail "README missing loom://primer or loom://savings resource documentation"
fi

# 10. loom-tool is installable via uvx (MCP server can start)
echo "[10] loom-mcp is installable via uvx"
if command -v uvx &>/dev/null; then
  if uvx --from loom-tool loom-mcp --help &>/dev/null 2>&1 || uvx --from loom-tool loom --version &>/dev/null 2>&1; then
    pass "loom-tool installable via uvx"
  else
    fail "uvx --from loom-tool failed (check PyPI: loom-tool)"
  fi
else
  skip "uvx not found — install uv to verify (check 10 skipped)"
fi

echo ""
echo "=== Results: $PASSED passed, $FAILED failed, $SKIPPED skipped ==="
[ "$FAILED" -eq 0 ]
