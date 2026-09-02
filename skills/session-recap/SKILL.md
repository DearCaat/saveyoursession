---
name: session-recap
description: Review native agent sessions after they have been synchronized, produce concrete titles and recaps, and recommend retention or cleanup; do not rewrite transcripts or delete data.
---

# Session Recap

Use this skill when a user asks to review, summarize, retain, or mark saved
agent sessions for cleanup. Recap is a judgment task performed by the agent;
the session manager only supplies native paths, metadata, fingerprints, and
cleanup gates.

## Workflow

1. Run `python scripts/manager.py list` and record the scan time and returned
   count. Treat it as a changing snapshot.
2. For each logical session, read the native transcript through its indexed
   path or `status` output. Read enough of the conversation to identify both
   the actual request and the outcome.
3. Use genuine user and assistant messages as evidence. Exclude harness or
   system injection, recommended-plugin lists, environment context,
   skills/AGENTS instructions, local-command caveats, and exact test echoes.
   If no real user task remains, state the structural evidence explicitly.
4. Resolve Codex parent-child edges. Put sub-agent sessions under the parent
   `children`; do not count or present them as independent logical sessions.
5. For every logical session produce:
   - a specific `title`;
   - one sentence `recap` naming the real task, file, command, plugin, dataset,
     question, or result;
   - short evidence excerpts or record references;
   - one `decision`: `keep`, `cleanup-candidate`, or `uncertain`.

Do not use generic text such as “围绕某主题进行分析”. Do not infer value
from size, record count, or harness metadata alone. Ambiguous evidence remains
`uncertain`.

## Cleanup handoff

Show the complete report to the user before changing state. After explicit
confirmation, use the manager's cleanup-tag operation with the current
transcript fingerprint. Recap never deletes. A tag becomes eligible only after
72 hours with no fingerprint change; any change requires `re-review`, and a
second explicit user confirmation is required before deletion.

## Output

Keep `generated_at`/`scan_started_at`, dynamic logical and child counts,
reviewer identity, decisions, and evidence. Leave every harness-native
transcript unchanged.
