---
name: loom-analyze
description: Index the current repository with Loom. Runs tree-sitter over all supported files and builds the symbol graph in ~/.loom/loom.db.
---

$ARGUMENTS

Run `loom analyze .` to index the current repository, or `loom analyze <path>` for a specific directory.

After indexing, call `graph_stats()` to confirm node/edge counts, then `suggest_questions()` to surface investigation priorities.
