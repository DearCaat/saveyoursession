# saveyoursession

[中文文档](README.md)

An agent-facing session manager for Codex, Claude Code, Grok Build, and DeepSeek Harness (DSH). Each harness keeps its native session format while sessions can be listed, searched, synchronized, and restored across harnesses.

This is not an MCP server and does not convert transcripts into a shared format. It maintains a small index and syncs changed native files to a Hugging Face Dataset.

## Features

- `list`: list sessions from one or all harnesses
- `search`: search content and metadata across harnesses
- `sync`: archive and upload changed files
- `status`: inspect sync status
- `restore`: restore a native session into its harness directory
- Claude `SessionEnd` hook for automatic sync
- Windows Task Scheduler support for daily sync

Archives are separated by harness:

```text
~/.saveyoursession/archive/
  codex/<session-id>/...
  claude/<session-id>/...
  grok-build/<session-id>/...
  dsh/<session-id>/...
```

## Install directly from GitHub

No manual clone is required. Each harness fetches and caches the plugin from GitHub.

### Claude Code

```bash
claude plugin marketplace add DearCaat/saveyoursession
claude plugin install saveyoursession@saveyoursession
claude plugin enable saveyoursession@saveyoursession
```

Restart Claude Code after installation. The `SessionEnd` hook syncs Claude sessions.

### Codex

```bash
codex plugin marketplace add DearCaat/saveyoursession --ref main
codex plugin add saveyoursession@saveyoursession
```

Open a new Codex session after installation or update.

### Grok Build

```bash
grok plugin install https://github.com/DearCaat/saveyoursession.git --trust
grok plugin list
```

The plugin scans native sessions under `$GROK_HOME/sessions`.

### DeepSeek Harness (DSH)

The DSH bundle is under `harnesses/dsh`:

```bash
dsh plugin --profile web add https://github.com/DearCaat/saveyoursession/tree/main/harnesses/dsh
dsh web
```

It registers `save_session_list`, `save_session_search`, `save_session_sync`, and `save_session_restore`, plus matching `/save-session-*` commands.

## HF Dataset configuration

Each harness configures its own local credentials. The public repository contains no tokens.

Create `config/local.env` in the plugin cache directory:

```env
HF_DATASET_REPO=Dearcat/agent_session
HF_TOKEN=hf_...
```

You may also use the `HF_DATASET_REPO`, `HF_TOKEN`, or `HF_TOKEN_FILE` environment variables.

Install dependencies before first use:

```bash
python -m pip install -r requirements.txt
```

## How it works

Each harness skill, hook, or bundle calls `scripts/manager.py`. Native files are copied to `archive/<harness>/<session-id>/`; `index.json` stores paths, timestamps, and hashes. Sync is idempotent and uploads only changed files. The first sync creates the local archive and uploads it to the HF Dataset.

## Agent commands

Read-only:

```bash
python scripts/manager.py list
python scripts/manager.py list --harness codex
python scripts/manager.py search "keyword"
python scripts/manager.py status codex <session-id>
```

Write operations:

```bash
python scripts/manager.py sync
python scripts/manager.py restore codex <session-id>
python scripts/manager.py restore codex <session-id> --target-root <directory>
```

## Automatic sync

Claude's `SessionEnd` hook syncs automatically. Install the Windows daily task:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\install_windows_schedule.ps1
```

## Updates

```bash
# Claude Code
claude plugin marketplace update saveyoursession
claude plugin update saveyoursession@saveyoursession

# Codex
codex plugin marketplace upgrade saveyoursession
codex plugin add saveyoursession@saveyoursession
```

Re-run the respective GitHub install command for Grok and DSH.

## Troubleshooting

- Sessions missing: check `CODEX_HOME`, `CLAUDE_HOME`, `GROK_BUILD_HOME`, and `DSH_HOME`.
- HF upload fails: check `config/local.env` and install `requirements.txt`.
- Claude hook inactive: restart Claude Code and re-enable the plugin.
- Close the target harness before restore to avoid overwriting files in use.

## Environment overrides

Override default paths with `SAVEYOURSESSION_ROOT`, `CODEX_HOME`, `CLAUDE_HOME`, `GROK_BUILD_HOME`, and `DSH_HOME`.

## License

MIT
