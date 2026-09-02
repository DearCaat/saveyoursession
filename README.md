# saveyoursession

[English documentation](README.en.md)

面向 agent 的会话管理插件，支持 Codex、Claude Code、Grok Build 和 DeepSeek Harness（DSH）。

每个 harness 保留自己的原生会话格式。插件提供跨 harness 的会话列表、搜索、同步和恢复。它不是 MCP 服务，也不会把不同 harness 的 transcript 转换成统一格式。

## 功能

- `list`：列出一个或全部 harness 的会话
- `search`：跨 harness 搜索会话内容和元数据
- `sync`：直接上传变化的原生会话文件
- `status`：查看会话同步状态
- `restore`：恢复到对应 harness 的原生目录
- Codex、Claude Code、Grok Build `SessionEnd` hook 自动同步
- Windows Task Scheduler 定期同步
- Ubuntu 22.04 systemd user timer 默认每 12 小时同步

同步时会从各 harness 的原生路径直接读取文件并上传；不会复制、移动或改写原生 transcript。插件本地只保存轻量的索引和 `metadata.json`（标题、预览、首条用户消息或摘要，以及 `created_at`/`updated_at`）：

```text
~/.saveyoursession/
  source.json
  index.json
  control.json                  # 可选的本地排除策略
  metadata/<source-id>/<harness>/<session-id>/<locator-hash>/metadata.json
```

Codex 优先使用其本地线程数据库的时间字段；其余 harness 或字段缺失时回退为原生会话文件的 `ctime`/`mtime`。注意 Linux 的 `ctime` 是 inode 元数据变更时间，不保证是严格的创建时间；它只是没有 harness 原生创建时间时的可用近似。

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

## Hugging Face Storage Bucket 配置

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

各 harness 的 skill、hook 或 bundle 调用 `scripts/manager.py`。首次同步会在 `source.json` 写入该安装位置持久化的 `source_id`。会话主键是 `source_id + harness + native_session_id + locator_hash`，所以同一 harness 在不同机器、WSL、容器或复制目录中即使出现相同原生 ID，也不会互相覆盖。同步直接从原生会话路径上传到 HF Bucket 的 `v1/<source-id>/<harness>/<session-id>/<locator-hash>/`，`index.json` 仅记录原生路径、远端对象路径、时间和 hash；不建立本地 raw archive。轻量 `metadata.json` 同时保存在本地 metadata 目录并上传到相同的远端会话目录。

同步是幂等的：每次通过 `hf sync` 与远端比较，只有远端不存在或内容变化时才传输；HF Storage Bucket/Xet 负责块级去重。恢复时从远端下载到匹配的 harness 原生目录；默认跳过本地已有文件，只有显式给出 `--target-root` 才允许覆盖目标文件。

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

## 三天 recap 与低价值会话

上传不会等待 recap：hook 或定时任务发现变化后立即上传。会话审查由独立的 `session-recap` skill 负责，Terra agent 按该 skill 读取原生 transcript、生成具体摘要并提出清理建议。同步脚本只提供列表、路径、时间、指纹和 cleanup gate，不判断语义价值，也不执行删除。

旧版 `index.json` 会保留为 `legacy_sessions`，不会和新 key 静默合并；先运行一次普通 `sync` 建立 source-aware 记录后，它们才会进入 recap 候选。

为后续排除预留的本地策略是 `~/.saveyoursession/control.json`：

```json
{
  "schema_version": 1,
  "exclusions": {
    "v1:<source-id>:codex:<native-session-id>:<locator-hash>": {
      "status": "excluded",
      "reason": "低价值"
    }
  }
}
```

普通 `sync` 遇到 `status: excluded` 会跳过该会话，不上传 transcript 或 metadata。云端控制对象的预留路径为 `control/exclusions.v1.json`；本版本尚不读取或写入它，因此 dry-run 不会改变远端。

## 自动同步

Codex 和 Claude Code 都使用插件的 `SessionEnd` hook。将下面配置写入各自插件缓存的 `config/local.env` 后启用：

```env
SAVEYOURSESSION_HOOK_ENABLED=true
```

Grok Build 插件也包含 `SessionEnd` hook；`grok plugin install ... --trust` 后启用插件，并在 Grok 的 `/hooks` 中确认它已加载。DSH 目前只提供 bundle 命令，没有已验证的 session-end hook 实现。

Codex 的 `SessionEnd` hook 有 **3 秒硬时间限制**。当前 hook 对同步子进程最多只给 2 秒，作为 best-effort；不要把 hook 当作远端写入成功的确认。定时任务会再次扫描并重试，作为可靠的最终上传路径。若以后实现真正的异步队列，hook 也应只负责写入队列，上传由独立 worker 完成。

Claude 的 `SessionEnd` hook 以 `async: true` 调度，会自动同步；进程结束前未完成的上传仍由定时任务补传。安装 Windows 定时任务：

Hook 只调用 `python3`，并在 `PLUGIN_ROOT`/`CLAUDE_PLUGIN_ROOT` 未设置或 `python3` 不存在时直接成功返回，不会阻塞会话结束。若日志仍出现 `/hooks/sync_*.py` 或 `python: not found`，说明 harness 仍加载旧的 0.1.4 缓存；升级到 0.1.5（重新安装插件并重启 harness）后再检查 hook。

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\install_windows_schedule.ps1
```

### Ubuntu 22.04 / WSL：systemd user timer

这里选择 systemd user timer，而不是 cron：`Persistent=true` 会在 WSL 实例离线而错过计划时间后，于 user manager 下次可用时补跑一次。WSL 必须已启用 systemd；若 WSL 完全未启动，任何 Linux 内部调度器都不能在准确时刻运行。

以下命令只安装 unit 和环境模板，并执行 `daemon-reload`；**不会创建已启用的定时任务，也不会立即同步**：

```bash
bash scripts/install_linux_schedule.sh --python python3
```

默认在 `03:00` 和 `15:00` 运行。可用 `--time HH:MM` 改第一个锚点（第二次永远相隔 12 小时），例如 `--time 08:30` 对应 `08:30` 与 `20:30`。

脚本创建 `~/.config/saveyoursession/sync.env`（权限为 owner-only），其中仅设置插件根目录和 Python。把 `HF_TOKEN` 留在插件的 `config/local.env`，或配置 `HF_TOKEN_FILE`；不要把 token 写入该文件或 systemd unit。确认路径和凭据后，显式启用：

```bash
systemctl --user enable --now saveyoursession-sync.timer
```

要让 timer 在注销后仍可运行，执行 `loginctl enable-linger "$USER"`。查看计划与日志：

```bash
systemctl --user list-timers saveyoursession-sync.timer
journalctl --user -u saveyoursession-sync.service
tail -f ~/.local/state/saveyoursession/sync.log
```

## 本地会话管理界面

可启动一个仅绑定 `127.0.0.1` 的轻量 Web UI，跨 harness 查看会话：

```bash
python3 scripts/web_ui.py --host 127.0.0.1 --port 8765
```

打开 <http://127.0.0.1:8765/> 后，每个 `session_key` 合并为一行，同时显示 Local/Remote 是否存在、同步状态（已同步、本地较新、云端较新、仅本地、仅云端或冲突）、两侧更新时间及时间差。标题/摘要优先使用原生 `first_user_message`、`preview` 或 recap；结构性空会话默认隐藏，可勾选显示并查看隐藏数量。点击行可分别查看 Local metadata 与 Remote metadata，并执行对应 Sync/Restore。UI 不转换或改写原生 transcript，也不应暴露到公网。

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
