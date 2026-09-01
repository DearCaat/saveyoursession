# SaveYourSession DSH bundle

This is the native DeepSeek Harness package entry point. Install this package
in a DSH profile; its `cordis.patch.yml` mounts `saveyoursession-dsh`, which
registers commands available inside DSH:

```text
/save-session-list [--harness codex|claude|grok-build|dsh]
/save-session-search <query>
/save-session-sync [--harness H] [--session-id ID]
/save-session-restore <harness> <session-id> [--target-root PATH]
```

The commands execute the shared `scripts/manager.py`. In a source checkout the
path is discovered automatically. For an installed package set
`SAVEYOURSESSION_MANAGER` to the shared manager path. HF settings are passed
through unchanged (`HF_DATASET_REPO`, `HF_TOKEN`, `HF_TOKEN_FILE`).
