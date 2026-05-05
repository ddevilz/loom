---
name: loom-savings
description: Show token savings from Loom cache hits — agent-written summaries vs auto-generated, all-time and recent.
---

$ARGUMENTS

Call `get_savings()` or load `loom://savings` resource.

Reports:
- `agent_hits` — summaries you wrote via `store_understanding` — file reads provably skipped
- `auto_hits` — structural summaries from `loom analyze` — may still need source for full context
- Total tokens saved all-time and in recent sessions
