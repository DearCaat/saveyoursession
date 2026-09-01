# saveyoursession

Agent-facing Codex plugin for managing native sessions from four harnesses:
Codex, Claude Code, Grok Build, and DeepSeek Harness (DSH).

The plugin provides a cross-harness index while retaining each harness's raw
session files independently. It archives locally first, then mirrors new files
to the configured Hugging Face Dataset. The local archive remains usable
offline.

Agent-facing operations exposed through each harness's native skill/command/tool entry:

- `list_sessions`
- `search_sessions`
- `session_status`
- `sync_session`
- `sync_all`
- `restore_session`

This plugin is intended to be enabled and called by an agent, not operated as a
human-facing command-line UI.

## Hugging Face sync

Set `HF_DATASET_REPO=Dearcat/agent_session`. The plugin reads the token at
runtime from `HF_TOKEN_FILE`; if omitted, it probes the Windows path
`C:\Users\tangwenhao\Downloads\token.txt` (and its WSL mount). The token is
never written to the archive/index or printed. `HF_TOKEN` may be used instead
of a file when the harness provides secrets through its environment.

On Windows, register a daily scan with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_schedule.ps1
```
