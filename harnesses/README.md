# Harness adapters

Each directory is an installation-facing entry point for one harness. The
adapters call the shared `scripts/manager.py` and never rewrite the native
session format.

The current bundle covers:

- `codex/`
- `claude/`
- `grok-build/`
- `dsh/`

The DSH adapter can import native Codex/Claude sessions through the same
archive. Native DSH UI integration should be packaged as a DSH bundle patch;
the local archive path is configurable with `DSH_HOME`.
