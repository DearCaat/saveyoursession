#!/usr/bin/env python3
"""Best-effort Grok Build SessionEnd hook for saveyoursession.

Grok Build exposes the native session ID as GROK_SESSION_ID (and in the hook
JSON payload).  This hook deliberately fails open: scheduled full sync retries
any local archive or remote upload that did not finish during session teardown.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_TRUE = {"1", "true", "yes", "on"}


def _enabled(plugin_root: Path) -> bool:
    value = os.environ.get("SAVEYOURSESSION_HOOK_ENABLED", "").strip().lower()
    if value:
        return value in _TRUE
    try:
        for line in (plugin_root / "config" / "local.env").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("SAVEYOURSESSION_HOOK_ENABLED="):
                return line.split("=", 1)[1].strip().strip("\"'").lower() in _TRUE
    except OSError:
        pass
    return False


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    if not _enabled(plugin_root):
        return 0
    session_id = os.environ.get("GROK_SESSION_ID")
    try:
        payload = json.load(sys.stdin)
        session_id = session_id or payload.get("sessionId") or payload.get("session_id") or payload.get("id")
    except (json.JSONDecodeError, OSError):
        pass
    if not session_id:
        return 0
    manager = plugin_root / "scripts" / "manager.py"
    if not manager.is_file():
        return 0
    try:
        requested_timeout = int(os.environ.get("SAVEYOURSESSION_GROK_HOOK_TIMEOUT", "8"))
        timeout = min(max(requested_timeout, 1), 8)
        subprocess.run(
            [sys.executable, str(manager), "sync", "--harness", "grok-build", "--session-id", str(session_id)],
            cwd=plugin_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
