---
name: loom-topology
description: Surface architectural insights — god nodes, surprising cross-module connections, community cohesion scores, and suggested investigation questions.
---

$ARGUMENTS

Calls in sequence:
1. `suggest_questions(limit=7)` — dead code, bridge nodes, undocumented hot functions, low-cohesion communities
2. `get_surprising_connections(limit=10)` — non-obvious cross-module CALLS edges with human-readable explanations
3. `get_community_cohesion()` — cohesion score per cluster (< 0.2 = refactor candidate)
4. `god_nodes(limit=10)` — most-called functions (unofficial entry points / god functions)

Use this at the start of a refactoring session to understand architectural health.
