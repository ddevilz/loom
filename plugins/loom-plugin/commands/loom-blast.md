---
name: loom-blast
description: Show the transitive callers of a function — everything that breaks if this changes. Uses the impact-analysis skill for full risk assessment.
---

$ARGUMENTS

Call `get_blast_radius("<node_id>", depth=3)` to see all transitive callers.

For full risk assessment including community cohesion and surprising connections, use the `impact-analysis` skill instead.

Node ID format: `function:src/auth.py:validate_token`
Find node IDs with `search_code("<name>")`.
