Analyze the blast radius of a proposed change to a symbol in the Loom knowledge graph.

## Usage
Provide the symbol you want to analyze:
- **Symbol**: fully qualified name (e.g. `loom.linker.SemanticLinker.link`)
- **Change type**: signature change | removal | semantic change | rename

## What this command does

1. **Queries the graph** — runs a BFS over *incoming* `CALLS` edges from the target symbol (callers, not callees).
2. **Checks IMPLEMENTS/SPECIFIES edges** — finds any doc spec nodes that reference this symbol. If the symbol changes, those specs may become stale (`VIOLATES`).
3. **Produces a blast radius report** with:
   - Direct callers (depth 1)
   - Transitive callers (depth 2+)
   - Spec nodes at risk of becoming VIOLATES
   - Estimated test surface (test files that import the symbol)

## Graph traversal rules (enforce these)
- Follow **incoming** `CALLS` edges only (who calls the target — not what the target calls).
- Do not follow `DEPENDS_ON` edges for blast radius — module-level deps are too coarse.
- Stop BFS at depth 5 unless `--deep` is specified.

## Output format
```
Symbol: <symbol>
Change type: <change_type>

Direct callers (depth 1):
  - <caller_1>
  - <caller_2>

Transitive callers (depth 2-5):
  - <caller_3> (via <caller_1>)

Spec nodes at risk:
  - <doc_node> [SPECIFIES → <symbol>]

Test surface:
  - tests/test_<module>.py

Risk summary: LOW | MEDIUM | HIGH
```

Risk is HIGH if: >5 transitive callers OR any spec node references the symbol.
Risk is MEDIUM if: 2–5 callers and no spec nodes.
Risk is LOW if: ≤1 caller and no spec nodes.
