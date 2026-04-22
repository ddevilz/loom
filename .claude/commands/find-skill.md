Find the right skill for the current task in the Loom codebase.

## How to use
Describe what you're about to do, and this command will recommend the best skill(s) to activate first.

## Decision tree

**Are you debugging a failing test, import error, or unexpected behavior?**
→ Activate `systematic-debugging` (obra/superpowers) BEFORE touching any code.
   It enforces a 4-phase root cause process. Do not skip to fixing — diagnose first.

**Are you planning a new feature or MCP tool?**
→ Activate `brainstorming` (obra/superpowers) to spec it out before writing anything.
   Then `writing-plans` to break it into bite-sized tasks.

**Are you implementing something on the MCP server (`mcp/server.py`)?**
→ Activate `mcp-builder` (Anthropic built-in: `/mnt/skills/examples/mcp-builder/SKILL.md`).
   It covers FastMCP patterns, Pydantic schemas, tool annotations, and the Python SDK.

**Are you writing new code (any file)?**
→ Activate `test-driven-development` (obra/superpowers).
   Write the failing test first. This is non-optional for graph traversal logic.

**Are all bugs fixed and the smoke test is passing?**
→ Activate `finishing-a-development-branch` (obra/superpowers) to ship v0.1.

**Are you writing docs, README, or HN launch content?**
→ Activate `doc-coauthoring` (Anthropic built-in: `/mnt/skills/examples/doc-coauthoring/SKILL.md`).

**Are you preparing a PR or reviewing a diff?**
→ Activate `requesting-code-review` then `receiving-code-review` (obra/superpowers).

**Are you working on security scanning (Sentinel tier)?**
→ Fetch Trail of Bits skills: https://github.com/trailofbits/claude-skills

## Quick reference

Installed and ready (no install needed):
- `mcp-builder` → `/mnt/skills/examples/mcp-builder/SKILL.md`
- `doc-coauthoring` → `/mnt/skills/examples/doc-coauthoring/SKILL.md`
- `skill-creator` → `/mnt/skills/examples/skill-creator/SKILL.md`

Requires install (obra/superpowers):
```bash
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```
Skills included: `systematic-debugging`, `test-driven-development`,
`finishing-a-development-branch`, `brainstorming`, `writing-plans`,
`requesting-code-review`, `receiving-code-review`, `using-git-worktrees`

Full curated list: `.claude/skills.md`
