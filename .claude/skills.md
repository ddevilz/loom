# Loom — Skills Reference

A curated map of skills for Claude Code to use when working on Loom.
Skills are organized by the task context in which they should be activated.

---

## How to Install Skills

### From obra/superpowers (highest priority — install this first)
The most battle-tested community skill suite. Covers the full dev workflow.

```bash
# In Claude Code
/plugin marketplace add obra/superpowers-marketplace
/plugin install superpowers@superpowers-marketplace
```

Or manually fetch the install instructions:
```
https://raw.githubusercontent.com/obra/superpowers/refs/heads/main/.opencode/INSTALL.md
```

Skills included that matter for Loom: `systematic-debugging`, `test-driven-development`,
`finishing-a-development-branch`, `brainstorming`, `requesting-code-review`,
`receiving-code-review`, `using-git-worktrees`, `writing-plans`

---

## Skills by Task Context

### Debugging (BUG-1 through BUG-4 and future regressions)

| Skill | Source | Install |
|---|---|---|
| `systematic-debugging` | obra/superpowers | `/plugin install superpowers@superpowers-marketplace` |
| `root-cause-tracing` | obra/superpowers (bundled in systematic-debugging) | — |
| `defense-in-depth` | obra/superpowers (bundled in systematic-debugging) | — |

**When to activate:** Any `pytest` failure, `ImportError`, silent fallback behavior,
or unexpected graph state in FalkorDB. The systematic-debugging skill enforces a
4-phase root cause process — important for Loom's explicit-failure-over-silent-fallback philosophy.

---

### MCP Server Development (FastMCP tools, new capabilities)

| Skill | Source | Install |
|---|---|---|
| `mcp-builder` | Anthropic (built-in) | Pre-installed at `/mnt/skills/examples/mcp-builder/` |

**When to activate:** Adding new `@mcp.tool` functions, designing input schemas (Pydantic v2),
adding tool annotations (`readOnlyHint`, `destructiveHint`), or debugging MCP transport issues.
References the FastMCP Python guide and MCP spec directly.

---

### New Feature Planning (before writing any code)

| Skill | Source | Install |
|---|---|---|
| `brainstorming` | obra/superpowers | `/plugin install superpowers@superpowers-marketplace` |
| `writing-plans` | obra/superpowers | — |

**When to activate:** Any "let's add X to Loom" conversation. The brainstorming skill
forces spec-first thinking with explicit sign-off before implementation — critical for
solo engineering where unplanned scope creep is the main risk.

---

### Test-Driven Development

| Skill | Source | Install |
|---|---|---|
| `test-driven-development` | obra/superpowers | `/plugin install superpowers@superpowers-marketplace` |

**When to activate:** Adding new MCP tools, new linker edge types, or new graph traversal
queries. TDD is especially important for graph logic — red/green cycles on FalkorDB queries
catch incorrect Cypher before it silently returns wrong blast radius results.

---

### Shipping v0.1 (finishing the launch branch)

| Skill | Source | Install |
|---|---|---|
| `finishing-a-development-branch` | obra/superpowers | `/plugin install superpowers@superpowers-marketplace` |

**When to activate:** After all 4 bugs are fixed and smoke test passes. This skill
verifies tests, offers merge/PR/keep/discard options, and cleans up the worktree.
Pair with the `/smoke-test` slash command.

---

### Code Review

| Skill | Source | Install |
|---|---|---|
| `requesting-code-review` | obra/superpowers | `/plugin install superpowers@superpowers-marketplace` |
| `receiving-code-review` | obra/superpowers | — |

**When to activate:** Before any PR to main. The requesting skill prepares diffs with
context; the receiving skill helps process feedback without defensive sycophancy.

---

### Security (Sentinel paid tier, dependency scanning)

| Skill | Source | Install |
|---|---|---|
| `owasp-security` | Trail of Bits / community | See: https://github.com/trailofbits/claude-skills |
| `systematic-debugging` | obra/superpowers | — (covers secure code paths too) |

**When to activate:** When building the Sentinel compliance intelligence product,
reviewing PyNaCl (Ed25519 signing) usage in Toolmark, or auditing FalkorDB query
construction for injection risks.

Install Trail of Bits skills:
```
https://github.com/trailofbits/claude-skills
```

---

### Documentation & Launch Content

| Skill | Source | Install |
|---|---|---|
| `doc-coauthoring` | Anthropic (built-in) | Pre-installed at `/mnt/skills/examples/doc-coauthoring/` |
| `devmarketing-skills` | Community | See: https://github.com/VoltAgent/awesome-agent-skills |

**When to activate:**
- `doc-coauthoring` → Writing the Loom README, HN launch post, YC S26 application narrative
- `devmarketing-skills` → HN strategy, technical tutorial drafts, docs-as-marketing for the
  "Loom understands your codebase" positioning

---

### Keeping CLAUDE.md Fresh

| Skill | Source | Install |
|---|---|---|
| `review-claudemd` | Community (BehiSecc/awesome-claude-skills) | See: https://github.com/BehiSecc/awesome-claude-skills |

**When to activate:** After major refactors, after a bug is resolved (to close it in
the bugs section), or periodically to ensure CLAUDE.md reflects current repo state.

---

### Graph Database (FalkorDB query patterns)

| Skill | Source | Notes |
|---|---|---|
| `postgres` | Community | Structural reference only — FalkorDB uses Cypher, not SQL, but the query safety patterns (read-only guards, parameterization) are directly applicable |

Source: https://github.com/BehiSecc/awesome-claude-skills

---

## Skill Priority Order for Loom Sessions

When multiple skills could apply, prefer this order:

1. `systematic-debugging` if any test is failing or behavior is wrong
2. `brainstorming` if about to write new code
3. `test-driven-development` during implementation
4. `mcp-builder` when the work is specifically on MCP tool interfaces
5. `finishing-a-development-branch` when work is complete and ready to ship

---

## Community Skill Registries to Browse

| Registry | URL | Notes |
|---|---|---|
| Anthropic official | https://github.com/anthropics/skills | Production-quality reference skills |
| obra/superpowers | https://github.com/obra/superpowers | Best dev workflow suite, 88k+ stars |
| awesome-claude-skills | https://github.com/travisvn/awesome-claude-skills | Curated index |
| VoltAgent collection | https://github.com/VoltAgent/awesome-agent-skills | Official vendor skills (Sentry, Stripe, etc.) |
| SkillsMP marketplace | https://skillsmp.com | 500k+ skills, searchable |
| Trail of Bits security | https://github.com/trailofbits/claude-skills | Security-focused, high quality |

---

## Writing Loom-Specific Skills

If you need a Loom-specific skill (e.g., `loom-graph-query`, `loom-linker-debug`),
use the built-in `skill-creator` skill:

```bash
# Pre-installed
/mnt/skills/examples/skill-creator/SKILL.md
```

Place custom skills in `.claude/skills/` within the Loom repo and reference them here.
