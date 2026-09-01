# saveyoursession

Agent-facing Codex plugin for managing native sessions from four harnesses:
Codex, Claude Code, Grok Build, and DeepSeek Harness (DSH).

Install this same directory into each harness. Native session files remain in
their original format; the shared index only provides cross-harness listing and
search. The bundled `config/hf_token.txt` is used for the private
`Dearcat/agent_session` Dataset and is excluded from Git commits.

## Install

Codex: add this directory as a local plugin and enable `saveyoursession`; the
skill is `skills/saveyoursession/SKILL.md`.

Claude Code:

```powershell
claude --plugin-dir D:\twh\workspace\save_your_session
```

Grok Build:

```bash
grok plugin validate D:\twh\workspace\save_your_session
grok plugin install D:\twh\workspace\save_your_session --trust
```

DeepSeek Harness:

```bash
dsh plugin --profile web add D:\twh\workspace\save_your_session\harnesses\dsh
dsh web
```

## Agent operations

```bash
python scripts/manager.py list
python scripts/manager.py search "keyword"
python scripts/manager.py sync
python scripts/manager.py restore <harness> <session-id>
```

On Windows, register daily sync with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_schedule.ps1
```

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
