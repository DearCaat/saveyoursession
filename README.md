# saveyoursession

给 agent 用的会话管理插件：让 Codex、Claude Code、Grok Build 和 DeepSeek Harness（DSH）各自保存原生会话，并提供跨 harness 的查看、搜索、同步和恢复。

An agent-facing session manager for Codex, Claude Code, Grok Build, and DeepSeek Harness (DSH). Each harness keeps its native format while sessions can be listed, searched, synchronized, and restored across harnesses.

本插件不是 MCP 服务，也不要求人工整理统一 transcript 格式。插件只维护轻量索引，并把变化的原生文件同步到 Hugging Face Dataset。

This is not an MCP server and does not convert transcripts into a shared format. It maintains a small index and syncs changed native files to a Hugging Face Dataset.

## 功能 | Features

- `list`：列出一个或全部 harness 的会话 / list sessions from one or all harnesses
- `search`：跨 harness 搜索内容和元数据 / search content and metadata across harnesses
- `sync`：归档并上传变化文件 / archive and upload changed files
- `status`：查看归档状态 / inspect sync status
- `restore`：恢复到对应 harness 的原生目录 / restore into a native harness directory
- Claude `SessionEnd` hook 自动同步 / automatic sync through the Claude `SessionEnd` hook
- Windows Task Scheduler 每日同步 / daily sync through Windows Task Scheduler

## 安装：直接使用 GitHub | Install directly from GitHub

不需要先手动 clone；各 harness 会从 GitHub 获取并缓存插件。

No manual clone is required; each harness fetches and caches the plugin from GitHub.

### Claude Code

```bash
claude plugin marketplace add DearCaat/saveyoursession
claude plugin install saveyoursession@saveyoursession
claude plugin enable saveyoursession@saveyoursession
```

安装后重启 Claude Code。SessionEnd hook 会同步 Claude 会话。

Restart Claude Code after installation. The SessionEnd hook syncs Claude sessions.

### Codex

```bash
codex plugin marketplace add DearCaat/saveyoursession --ref main
codex plugin add saveyoursession@saveyoursession
```

安装或更新后重新打开 Codex session。

Open a new Codex session after installation or update.

### Grok Build

```bash
grok plugin install https://github.com/DearCaat/saveyoursession.git --trust
grok plugin list
```

插件从 `$GROK_HOME/sessions` 扫描原生会话。

The plugin scans native sessions under `$GROK_HOME/sessions`.

### DeepSeek Harness（DSH）

DSH bundle 位于 `harnesses/dsh` 子目录。

The DSH bundle is under `harnesses/dsh`:

```bash
dsh plugin --profile web add https://github.com/DearCaat/saveyoursession/tree/main/harnesses/dsh
dsh web
```

它注册 `save_session_list`、`save_session_search`、`save_session_sync`、`save_session_restore` 工具，以及对应的 `/save-session-*` 命令。

It registers `save_session_list`, `save_session_search`, `save_session_sync`, and `save_session_restore`, plus matching `/save-session-*` commands.

## HF Dataset 配置 | HF Dataset configuration

每个安装了插件的 harness 独立配置本地凭据。公开仓库不包含 token。

Each harness configures its own local credentials. The public repository contains no tokens.

在插件缓存目录中创建 `config/local.env`：

Create `config/local.env` in the plugin cache directory:

```env
HF_DATASET_REPO=Dearcat/agent_session
HF_TOKEN=hf_...
```

也可以使用环境变量 `HF_DATASET_REPO`、`HF_TOKEN` 或 `HF_TOKEN_FILE`。

You may also use the `HF_DATASET_REPO`, `HF_TOKEN`, or `HF_TOKEN_FILE` environment variables.

首次使用前安装依赖：

Install dependencies before first use:

```bash
python -m pip install -r requirements.txt
```

## 工作原理 | How it works

各 harness 的 skill、hook 或 bundle 调用 `scripts/manager.py`。会话原文件复制到 `archive/<harness>/<session-id>/`，`index.json` 记录路径、时间和 hash。同步是幂等的，只上传变化文件；首次同步会创建本地归档并上传到 HF Dataset。

Each harness skill, hook, or bundle calls `scripts/manager.py`. Native files are copied to `archive/<harness>/<session-id>/`; `index.json` stores paths, timestamps, and hashes. Sync is idempotent and uploads only changed files. The first sync creates the local archive and uploads it to the HF Dataset.

## Agent 调用 | Agent commands

只读操作 / Read-only:

```bash
python scripts/manager.py list
python scripts/manager.py list --harness codex
python scripts/manager.py search "关键词"
python scripts/manager.py status codex <session-id>
```

写操作 / Write operations:

```bash
python scripts/manager.py sync
python scripts/manager.py restore codex <session-id>
python scripts/manager.py restore codex <session-id> --target-root <目录>
```

## 自动同步 | Automatic sync

Claude 的 `SessionEnd` hook 会自动同步。Windows 每日任务：

Claude's `SessionEnd` hook syncs automatically. Install the Windows daily task:

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\install_windows_schedule.ps1
```

## 更新 | Updates

```bash
# Claude Code
claude plugin marketplace update saveyoursession
claude plugin update saveyoursession@saveyoursession

# Codex
codex plugin marketplace upgrade saveyoursession
codex plugin add saveyoursession@saveyoursession
```

Grok 和 DSH 重新执行各自的 GitHub 安装命令。

Re-run the respective GitHub install command for Grok and DSH.

## 故障排查 | Troubleshooting

- 找不到会话 / Sessions missing：检查 `CODEX_HOME`、`CLAUDE_HOME`、`GROK_BUILD_HOME`、`DSH_HOME`。
- HF 上传失败 / HF upload fails：检查 `config/local.env`，并确认已安装 `requirements.txt`。
- Claude hook 未生效 / Claude hook inactive：重启 Claude Code，并重新 enable 插件。
- 恢复前先关闭目标 harness / Close the target harness before restore，避免覆盖正在写入的文件 / to avoid overwriting files in use。

## 环境变量覆盖 | Environment overrides

`SAVEYOURSESSION_ROOT`、`CODEX_HOME`、`CLAUDE_HOME`、`GROK_BUILD_HOME`、`DSH_HOME` 可覆盖默认路径。

Override default paths with `SAVEYOURSESSION_ROOT`, `CODEX_HOME`, `CLAUDE_HOME`, `GROK_BUILD_HOME`, and `DSH_HOME`.

## License

MIT

