# saveyoursession

给 agent 用的会话管理插件：让 Codex、Claude Code、Grok Build 和 DeepSeek Harness（DSH）各自保存原生会话，同时提供跨 harness 的查看、搜索、同步和恢复。

它不是 MCP 服务，也不要求人手工整理统一格式。每个 harness 继续读写自己的会话文件；插件只维护一个轻量索引，并把归档文件同步到 Hugging Face Dataset。

## 能做什么

- `list`：列出一个或全部 harness 的会话
- `search`：跨 harness 搜索会话内容和元数据
- `sync`：归档本地会话，并上传变化文件到 HF Dataset
- `status`：查看某个会话的归档状态
- `restore`：把原生会话文件放回对应 harness 的目录
- Claude Code `SessionEnd` hook：会话结束时自动触发同步
- Windows Task Scheduler：按天执行全量扫描和同步

目录按 harness 分开保存：

```text
~/.saveyoursession/archive/
  codex/<session-id>/...
  claude/<session-id>/...
  grok-build/<session-id>/...
  dsh/<session-id>/...
```

## 安装：直接使用 GitHub 仓库

不需要先手动 clone。各 harness 会从 GitHub 获取并缓存插件。

### Claude Code

```bash
claude plugin marketplace add DearCaat/saveyoursession
claude plugin install saveyoursession@saveyoursession
claude plugin enable saveyoursession@saveyoursession
```

### Codex

```bash
codex plugin marketplace add DearCaat/saveyoursession --ref main
codex plugin add saveyoursession@saveyoursession
```

安装或更新后重新打开一个 session。

### Grok Build

```bash
grok plugin install https://github.com/DearCaat/saveyoursession.git --trust
grok plugin list
```

插件会从 `$GROK_HOME/sessions` 扫描 Grok 原生会话。

### DeepSeek Harness（DSH）

DSH bundle 位于仓库的 `harnesses/dsh` 子目录：

```bash
dsh plugin --profile web add https://github.com/DearCaat/saveyoursession/tree/main/harnesses/dsh
dsh web
```

它注册 `save_session_list`、`save_session_search`、`save_session_sync`、`save_session_restore` 工具，以及对应的 `/save-session-*` 命令。

## 配置 HF Dataset

每个安装了插件的 harness 独立配置自己的本地凭据。公开仓库不包含 token。

在插件缓存目录或工作副本中创建 `config/local.env`：

```env
HF_DATASET_REPO=Dearcat/agent_session
HF_TOKEN=hf_...
```

也可以使用环境变量 `HF_DATASET_REPO`、`HF_TOKEN` 或 `HF_TOKEN_FILE`。

首次使用前安装 Python 依赖：

```bash
python -m pip install -r requirements.txt
```

## 工作原理

`scripts/manager.py` 是共享入口；各 harness 的 skill、hook 或 bundle 调用它。会话原文件复制到本地 `archive/<harness>/<session-id>/`，`index.json` 只记录路径、时间和 hash。同步具有幂等性，只上传变化文件；首次 `sync` 会产生本地归档并上传到 HF Dataset。

## Agent 调用

只读操作：

```bash
python scripts/manager.py list
python scripts/manager.py list --harness codex
python scripts/manager.py search "关键词"
python scripts/manager.py status codex <session-id>
```

写操作：

```bash
python scripts/manager.py sync
python scripts/manager.py restore codex <session-id>
python scripts/manager.py restore codex <session-id> --target-root <目录>
```

## 自动同步

Claude Code 的 `SessionEnd` hook 会自动同步 Claude 会话。Windows 每日任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_schedule.ps1
```

## 更新

```bash
# Claude Code
claude plugin marketplace update saveyoursession
claude plugin update saveyoursession@saveyoursession

# Codex
codex plugin marketplace upgrade saveyoursession
codex plugin add saveyoursession@saveyoursession
```

Grok 和 DSH 重新执行各自的 GitHub plugin install/add 命令获取最新版本。

## 故障排查

- 找不到会话：检查 `CODEX_HOME`、`CLAUDE_HOME`、`GROK_BUILD_HOME`、`DSH_HOME`。
- HF 上传失败：确认 `config/local.env` 中的 `HF_TOKEN` 和 `HF_DATASET_REPO`，并安装 `requirements.txt`。
- Claude hook 未生效：重启 Claude Code 或重新 enable 插件。
- 恢复前先确认目标 harness 已关闭，避免覆盖正在写入的原生文件。

## 开发与验证

```bash
python -m py_compile scripts/*.py hooks/*.py
claude plugin validate .
```

本地开发目录：`D:\twh\workspace\save_your_session`。

## License

MIT
