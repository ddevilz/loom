---
name: loom-delta
description: Show what changed since your last session — only the functions that were modified or added. Eliminates re-reading unchanged code.
---

$ARGUMENTS

Call `get_delta(previous_session_id="<id>")` with the session_id from your last `start_session()` call.

Or call `get_delta(agent_id="claude-code")` to find the most recent session for this agent type.

Returns context packets for changed/new nodes only, plus a list of deleted node IDs.
Unchanged nodes (87%+ in a typical session) are skipped — massive token savings.
