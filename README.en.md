# saveyoursession

[中文文档](README.md)

An agent-facing session manager for Codex, Claude Code, Grok Build, and DeepSeek Harness (DSH). Each harness keeps its native session format while sessions can be listed, searched, synchronized, and restored across harnesses.

This is not an MCP server and does not convert transcripts into a shared format. It maintains a small index and syncs changed native files to a Hugging Face Storage Bucket.

## Features

- `list`: list sessions from one or all harnesses
- `search`: search content and metadata across harnesses
- `sync`: upload changed native session files directly
- `status`: inspect sync status
- `restore`: restore a native session into its harness directory
- Codex, Claude Code, and Grok Build `SessionEnd` hooks for automatic sync
- Windows Task Scheduler support for periodic sync
- Ubuntu 22.04 systemd user timer support for a default 12-hour sync

Sync reads directly from each harness's native paths and uploads those files; it never copies, moves, or rewrites a native transcript. Locally, the plugin retains only a small index and `metadata.json` (title, preview, first user message or summary, and `created_at`/`updated_at`):

```text
~/.saveyoursession/
  source.json
  index.json
  control.json                  # optional local exclusion policy
  metadata/<source-id>/<harness>/<session-id>/<locator-hash>/metadata.json
```

Codex prefers timestamps from its local thread database; missing fields and other harnesses fall back to the native session file's `ctime`/`mtime`. On Linux, `ctime` is inode metadata-change time rather than a guaranteed creation time, so it is only the best available approximation when the harness has no native creation timestamp.

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

## Hugging Face Storage Bucket configuration

Each harness configures its own local credentials. The public repository contains no tokens.

Create `config/local.env` in the plugin cache directory:

```env
HF_BUCKET_URI=hf://buckets/Dearcat/agent-session
HF_TOKEN=hf_...
SAVEYOURSESSION_HOOK_ENABLED=true
```

You may also use `HF_BUCKET_URI`, `HF_TOKEN`, or `HF_TOKEN_FILE`. `HF_BUCKET_URI` defaults to `hf://buckets/Dearcat/agent-session`.
Set `SAVEYOURSESSION_HOOK_ENABLED=true` to enable automatic Claude `SessionEnd` sync; it is disabled by default.

Install dependencies before first use:

```bash
python -m pip install -r requirements.txt
```

## How it works

Each harness skill, hook, or bundle calls `scripts/manager.py`. On first sync, `source.json` persists an installation-specific `source_id`. A session key is `source_id + harness + native_session_id + locator_hash`, so matching native IDs from the same harness on different machines, WSL instances, containers, or copied directories cannot overwrite each other. Sync uploads directly from the native path to `v1/<source-id>/<harness>/<session-id>/<locator-hash>/` in the HF Bucket. `index.json` stores only native paths, remote object paths, timestamps, and hashes; no local raw archive is created. Lightweight `metadata.json` is retained locally and uploaded to the matching remote session directory.

Sync is idempotent: `hf sync` compares each source with the remote bucket and transfers only absent or changed remote data; HF Storage Bucket/Xet provides block-level deduplication. Restore downloads from HF into the matching harness's native directory. It skips an existing local file by default; supplying `--target-root` explicitly opts into overwriting target files.

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

## Three-day recap and low-value sessions

Upload does not wait for recap: hooks and scheduled sync upload changed native sessions immediately. Session review is handled by the separate `session-recap` skill, which instructs a Terra agent to read native transcripts, write concrete summaries, and recommend retention or cleanup. Sync scripts only expose listing, paths, timestamps, fingerprints, and cleanup gates; they do not make semantic value judgments or delete data.

An older `index.json` is retained as `legacy_sessions`, never silently merged into the new key scheme. Run a normal `sync` once to establish source-aware records before those sessions enter recap candidates.

The local exclusion-policy placeholder is `~/.saveyoursession/control.json`:

```json
{
  "schema_version": 1,
  "exclusions": {
    "v1:<source-id>:codex:<native-session-id>:<locator-hash>": {
      "status": "excluded",
      "reason": "low value"
    }
  }
}
```

Normal `sync` skips any session with `status: excluded`, including its transcript and metadata. The reserved cloud-control path is `control/exclusions.v1.json`; this version does not yet read or write it, so dry-run cannot change the remote.

## Automatic sync

Codex and Claude Code use the plugin `SessionEnd` hook. Enable it by adding this to each plugin cache's `config/local.env`:

```env
SAVEYOURSESSION_HOOK_ENABLED=true
```

The Grok Build plugin also bundles a `SessionEnd` hook. Install it with `--trust`, enable the plugin, and confirm that it is loaded in Grok's `/hooks` view. DSH currently provides bundle commands only; it has no verified session-end hook implementation.

Codex's `SessionEnd` hook has a **hard 3-second limit**. The current hook gives its sync subprocess at most two seconds as a best effort; do not treat hook completion as remote-write confirmation. The scheduled task rescans and retries, providing the reliable final-upload path. If a true asynchronous queue is added later, the hook should only enqueue locally and a separate worker should upload it.

Claude's `SessionEnd` hook is dispatched with `async: true`; any upload that does not finish before process teardown is retried by the scheduled sync. Install the Windows scheduled task:

Hooks invoke `python3` only. If `PLUGIN_ROOT`/`CLAUDE_PLUGIN_ROOT` is missing or `python3` is unavailable, they exit successfully and never block session shutdown. If logs still show `/hooks/sync_*.py` or `python: not found`, the harness is loading the old 0.1.4 cache; reinstall the 0.1.5 plugin and restart the harness before checking the hook again.

```powershell
powershell -ExecutionPolicy Bypass -File .\\scripts\\install_windows_schedule.ps1
```

### Ubuntu 22.04 / WSL: systemd user timer

This uses a systemd user timer rather than cron because `Persistent=true` catches up once when the WSL instance was offline at the scheduled time. WSL must have systemd enabled; if WSL itself is not running, no Linux-internal scheduler can run at the exact wall-clock time.

The following command writes the unit files and environment template and runs `daemon-reload`; it **does not enable a timer or run a sync**:

```bash
bash scripts/install_linux_schedule.sh --python python3
```

By default it runs at `03:00` and `15:00`. Use `--time HH:MM` to change the first anchor (the second is always 12 hours later); for example, `--time 08:30` runs at `08:30` and `20:30`.

The script creates `~/.config/saveyoursession/sync.env` with owner-only permissions. It contains only the plugin root and Python executable. Keep `HF_TOKEN` in the plugin's `config/local.env`, or configure `HF_TOKEN_FILE`; never place a token in this file or in a systemd unit. After confirming the paths and credentials, explicitly enable it:

```bash
systemctl --user enable --now saveyoursession-sync.timer
```

To keep the timer available after logout, run `loginctl enable-linger "$USER"`. Inspect its schedule and logs with:

```bash
systemctl --user list-timers saveyoursession-sync.timer
journalctl --user -u saveyoursession-sync.service
tail -f ~/.local/state/saveyoursession/sync.log
```

## Local session management UI

Start the dependency-free UI on localhost:

```bash
python3 scripts/web_ui.py --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765/>. Each source-aware `session_key` is shown as one logical row with Local/Remote existence, sync status (synced, local newer, remote newer, local-only, remote-only, or conflict), both timestamps, and their time delta. Titles/summaries prefer native `first_user_message`, `preview`, or recap. Structurally empty sessions are hidden by default; a checkbox reveals them and reports the hidden count. Expand a row to inspect Local metadata and Remote metadata separately, with Sync/Restore actions as applicable. The UI never rewrites or normalizes native transcripts and should not be exposed publicly.

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
