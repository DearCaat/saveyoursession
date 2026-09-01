#!/usr/bin/env python3
"""Grok Build adapter for the SaveYourSession shared manager.

This is intentionally a thin native-harness entry point: all discovery,
indexing, archive, HF upload, and restore behavior lives in scripts/manager.py.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
MANAGER = PLUGIN_ROOT / "scripts" / "manager.py"


def _grok_sessions_root() -> Path:
    """Return Grok's native session directory unless explicitly overridden."""
    configured = os.environ.get("GROK_BUILD_HOME")
    if configured:
        return Path(configured).expanduser()
    # Grok documents sessions under $GROK_HOME/sessions (default ~/.grok).
    grok_home = Path(os.environ.get("GROK_HOME", Path.home() / ".grok")).expanduser()
    return grok_home / "sessions"


def main(argv: list[str] | None = None) -> int:
    if not MANAGER.is_file():
        raise SystemExit(f"saveyoursession manager not found: {MANAGER}")
    args = list(sys.argv[1:] if argv is None else argv)
    # This adapter is the Grok-specific entry point.  Keep cross-harness views
    # available through the shared manager/skill, while making the common
    # Grok operations unambiguous and preventing an accidental full scan.
    if args and args[0] in {"list", "sync"} and "--harness" not in args:
        args[1:1] = ["--harness", "grok-build"]
    # The adapter owns the Grok root so agents do not need to know its layout.
    env = os.environ.copy()
    env.setdefault("GROK_BUILD_HOME", str(_grok_sessions_root()))
    proc = subprocess.run([sys.executable, str(MANAGER), *args], env=env)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
