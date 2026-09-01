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

## Codex (直接从 GitHub 安装)

不需要手动 clone。Codex 会把 GitHub 仓库作为 marketplace 源并缓存插件：

```bash
codex plugin marketplace add DearCaat/saveyoursession --ref main
codex plugin add saveyoursession@saveyoursession
```

安装后重启 Codex；技能会自动加载。

## Claude Code (直接从 GitHub 安装)

```powershell
claude plugin marketplace add DearCaat/saveyoursession
claude plugin install saveyoursession@saveyoursession
claude plugin enable saveyoursession@saveyoursession
```

重启 Claude Code 后生效；SessionEnd hook 会执行 Claude 会话同步。

## Grok Build (GitHub 源安装)

```powershell
grok plugin install https://github.com/DearCaat/saveyoursession.git --trust
grok plugin list
```

Grok discovers `skills/saveyoursession/SKILL.md`; its wrapper defaults to
`$GROK_HOME/sessions`.

## DeepSeek Harness (DSH，GitHub 源安装)

```powershell
dsh plugin --profile web add https://github.com/DearCaat/saveyoursession.git//harnesses/dsh
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
