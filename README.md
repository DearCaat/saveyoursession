# saveyoursession

[English documentation](README.en.md)

面向 agent 的会话管理插件，支持 Codex、Claude Code、Grok Build 和 DeepSeek Harness（DSH）。

每个 harness 保留自己的原生会话格式。插件提供跨 harness 的会话列表、搜索、同步和恢复。它不是 MCP 服务，也不会把不同 harness 的 transcript 转换成统一格式。

## 功能

- `list`：列出一个或全部 harness 的会话
- `search`：跨 harness 搜索会话内容和元数据
- `sync`：归档会话并上传变化文件
- `status`：查看会话同步状态
- `restore`：恢复到对应 harness 的原生目录
- Claude `SessionEnd` hook 自动同步
- Windows Task Scheduler 每日同步

本地归档按 harness 分开保存：

```text
~/.saveyoursession/archive/
  codex/<session-id>/...
  claude/<session-id>/...
  grok-build/<session-id>/...
  dsh/<session-id>/...
```

## 从 GitHub 直接安装

不需要手动 clone。各 harness 会直接从 GitHub 获取并缓存插件。

### Claude Code

```bash
claude plugin marketplace add DearCaat/saveyoursession
claude plugin install saveyoursession@saveyoursession
claude plugin enable saveyoursession@saveyoursession
```

安装后重启 Claude Code。SessionEnd hook 会同步 Claude 会话。

### Codex

```bash
codex plugin marketplace add DearCaat/saveyoursession --ref main
codex plugin add saveyoursession@saveyoursession
```

安装或更新后重新打开 Codex session。

### Grok Build

```bash
grok plugin install https://github.com/DearCaat/saveyoursession.git --trust
grok plugin list
```

插件从 `$GROK_HOME/sessions` 扫描 Grok 原生会话。

### DeepSeek Harness（DSH）

DSH bundle 位于仓库的 `harnesses/dsh` 子目录：

```bash
dsh plugin --profile web add https://github.com/DearCaat/saveyoursession/tree/main/harnesses/dsh
dsh web
```

它注册 `save_session_list`、`save_session_search`、`save_session_sync`、`save_session_restore` 工具，以及对应的 `/save-session-*` 命令。

## HF Dataset 配置

每个 harness 独立配置本地凭据。公开仓库不包含 token。

在插件缓存目录中创建 `config/local.env`：

```env
HF_BUCKET_URI=hf://buckets/Dearcat/agent-session
HF_TOKEN=hf_...
SAVEYOURSESSION_HOOK_ENABLED=true
```

也可以使用环境变量 `HF_BUCKET_URI`、`HF_TOKEN` 或 `HF_TOKEN_FILE`。`HF_BUCKET_URI` 默认是 `hf://buckets/Dearcat/agent-session`。
将 `SAVEYOURSESSION_HOOK_ENABLED=true` 写入 `config/local.env` 后，Claude 的 `SessionEnd` hook 才会自动同步；默认关闭。

首次使用前安装依赖：

```bash
python -m pip install -r requirements.txt
```

## 工作原理

各 harness 的 skill、hook 或 bundle 调用 `scripts/manager.py`。原生会话文件复制到 `archive/<harness>/<session-id>/`，`index.json` 记录路径、时间和 hash。

同步是幂等的，会同时比较本地归档和 HF 远端 hash；只有远端不存在或内容变化时才上传。对追加式 JSONL 会话，首次同步上传完整文件，后续只上传新增 chunk；非追加修改才重新上传完整文件。

## Agent 命令

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

Codex 和 Claude Code 都使用插件的 `SessionEnd` hook。将下面配置写入各自插件缓存的 `config/local.env` 后启用：

```env
SAVEYOURSESSION_HOOK_ENABLED=true
```

Grok Build 和 DSH 的 hook 入口随各自 bundle 提供；具体事件名取决于 harness 版本。安装后在对应 harness 中启用该 bundle 的 session-end hook。

Claude 的 `SessionEnd` hook 会自动同步。安装 Windows 每日任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\install_windows_schedule.ps1
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

Grok 和 DSH 重新执行各自的 GitHub 安装命令。

## 故障排查

- 找不到会话：检查 `CODEX_HOME`、`CLAUDE_HOME`、`GROK_BUILD_HOME`、`DSH_HOME`。
- HF 上传失败：检查 `config/local.env`，并确认已经安装 `requirements.txt`。
- Claude hook 未生效：重启 Claude Code，并重新 enable 插件。
- 恢复前先关闭目标 harness，避免覆盖正在写入的原生文件。

## 环境变量覆盖

可用 `SAVEYOURSESSION_ROOT`、`CODEX_HOME`、`CLAUDE_HOME`、`GROK_BUILD_HOME`、`DSH_HOME` 覆盖默认路径。

## 许可证

MIT
