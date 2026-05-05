---
name: loom-summaries
description: Show functions with agent-written summaries, most recently updated first. Reveals what agents have learned about the codebase.
---

$ARGUMENTS

Run `loom summaries --limit 20` to display the N most recently documented functions.

Each row shows: function name, source path, summary text (truncated to 70 chars).

To add summaries, call `store_understanding(node_id, summary)` or use the `document-code` skill.
