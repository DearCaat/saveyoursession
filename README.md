# saveyoursession

Agent-facing session backup and restore for Codex, Claude Code, Grok Build,
and DeepSeek Harness (DSH). Each harness keeps its native session format; a
small shared index enables cross-harness listing and search.

This public repository contains no credentials. Copy
`config/local.env.example` to `config/local.env` and fill in your own HF token.
The local file is ignored by Git.

## Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`
- Clone this public repository, for example to
  `D:\twh\workspace\save_your_session`
- `copy config\local.env.example config\local.env` and set `HF_TOKEN`

Verify the shared core:

```powershell
py .\scripts\manager.py list --limit 10
py .\scripts\manager.py sync
```

## Codex

Codex installs plugins from a marketplace snapshot. Put this checkout at
`plugins/saveyoursession` inside your personal marketplace, refresh it, then:

```bash
codex plugin add saveyoursession@personal
```

For local development, link `skills/saveyoursession` into the Codex skills
directory. Start a new Codex session and ask it to use `saveyoursession`.

## Claude Code

```powershell
claude plugin validate D:\twh\workspace\save_your_session
claude --plugin-dir D:\twh\workspace\save_your_session
```

For persistent installation, add this repository to a Claude marketplace,
then run `claude plugin install saveyoursession@<marketplace>` and
`claude plugin enable saveyoursession@<marketplace>`. The SessionEnd hook
performs a Claude-only sync.

## Grok Build

```powershell
grok plugin validate D:\twh\workspace\save_your_session
grok plugin install D:\twh\workspace\save_your_session --trust
grok plugin list
```

Grok discovers `skills/saveyoursession/SKILL.md`; its wrapper defaults to
`$GROK_HOME/sessions`.

## DeepSeek Harness (DSH)

```powershell
dsh plugin --profile web add D:\twh\workspace\save_your_session\harnesses\dsh
dsh web
```

The bundle registers `save_session_list`, `save_session_search`,
`save_session_sync`, and `save_session_restore`, plus `/save-session-*` aliases.

## Agent operations

```bash
python scripts/manager.py list
python scripts/manager.py list --harness codex
python scripts/manager.py search "keyword"
python scripts/manager.py sync
python scripts/manager.py status <harness> <session-id>
python scripts/manager.py restore <harness> <session-id>
```

The first `sync` creates the archive/index and uploads changed native files to
the HF Dataset. Register a daily Windows sync with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_schedule.ps1
```

Overrides: `SAVEYOURSESSION_ROOT`, `HF_DATASET_REPO`, `HF_TOKEN`, `HF_TOKEN_FILE`,
`CODEX_HOME`, `CLAUDE_HOME`, `GROK_BUILD_HOME`, and `DSH_HOME`.
