#!/usr/bin/env python3
"""Best-effort Codex SessionEnd hook for saveyoursession."""
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    enabled = os.environ.get("SAVEYOURSESSION_HOOK_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
    if not enabled:
        local_env = plugin_root / "config" / "local.env"
        try:
            for line in local_env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("SAVEYOURSESSION_HOOK_ENABLED="):
                    enabled = line.split("=", 1)[1].strip().strip('"\'').lower() in {"1", "true", "yes", "on"}
                    break
        except OSError:
            pass
    if not enabled:
        return 0
    manager = plugin_root / "scripts" / "manager.py"
    if not manager.exists():
        return 0
    try:
        subprocess.run([sys.executable, str(manager), "sync", "--harness", "codex"], cwd=str(plugin_root), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=int(os.environ.get("SAVEYOURSESSION_HOOK_TIMEOUT", "25")), check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
