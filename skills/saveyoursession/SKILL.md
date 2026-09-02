---
name: saveyoursession
description: "Manage native sessions across Codex, Claude Code, Grok Build, and DSH: list or search sessions across harnesses, sync their native files to Hugging Face, and restore a session into its matching harness. Use when an agent needs session continuity, backup, or cross-harness session lookup; do not convert transcripts between harness formats."
---

# SaveYourSession

This is an agent-facing session manager. Invoke the shared command through the
harness-native skill/entry point; it is not an MCP server. In shell commands,
`PLUGIN_ROOT` is the Codex plugin root and `CLAUDE_PLUGIN_ROOT` is the Claude
Code plugin root; use the first one that is defined.

## Rules

- Keep each harness's native files and directory layout separate.
- Use `python "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/scripts/manager.py" list`
  for a cross-harness view; add
  `--harness <name>` when the task is harness-specific.
- Run `python "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/scripts/manager.py" sync`
  for a scheduled/full scan, or add
  `--harness <name>` and `--session-id <id>` for one harness/session.
- Use `python "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/scripts/manager.py" search <query>`
  to search the shared index and any native content still present locally.
- Before restoring, run
  `python "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/scripts/manager.py" status <harness> <id>`;
  restore only into the matching harness unless the user explicitly supplies a
  target directory.
- Do not invent cross-harness transcript conversions. Cross-harness viewing is
  metadata/content search over native artifacts, not format unification.

## Config

Set `SAVEYOURSESSION_ROOT` to choose the local index/metadata directory. It
never contains a raw transcript archive: raw files remain in their harness's
native directory and are uploaded directly from there. The adapter roots can
be overridden with `CODEX_HOME`, `CLAUDE_HOME`,
`GROK_BUILD_HOME`, and `DSH_HOME`.

For Hugging Face sync, set `HF_BUCKET_URI=hf://buckets/Dearcat/agent-session`
and provide `HF_TOKEN` (or `HF_TOKEN_FILE`). The bucket backend uses `hf sync`
and Xet remote deduplication; `HF_DATASET_REPO` remains only as a legacy
fallback. Never expose the token in tool output or session content.

## Grok Build adapter

When running inside Grok Build, use the bundled adapter so the native Grok
session root is selected automatically:

```bash
python harnesses/grok-build/entrypoint.py list
python harnesses/grok-build/entrypoint.py search "query"
python harnesses/grok-build/entrypoint.py sync
```

The adapter delegates to `scripts/manager.py`; it does not convert Grok
artifacts or alter their native layout. Grok's documented session directory is
`$GROK_HOME/sessions/` (default `~/.grok/sessions/`).

The Claude Code plugin also runs a best-effort SessionEnd hook that executes
the Claude-only sync. A failed upload leaves the native session untouched and
is retried by the scheduled `sync` command.

## Recap

For session review and cleanup recommendations, use the separate
`session-recap` skill. This skill only manages native sessions and their
mechanical state; it does not perform semantic recap.
