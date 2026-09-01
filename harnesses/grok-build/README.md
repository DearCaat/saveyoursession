# Grok Build entry point

Grok Build loads this plugin through its standard `skills/` directory (the
official plugin docs also accept `.grok-plugin/plugin.json` and
`.claude-plugin/` manifests). The agent-facing adapter is
`entrypoint.py`; it delegates every operation to the shared `scripts/manager.py`
and always supplies `--harness grok-build` through the skill instructions.

Grok stores native sessions in `$GROK_HOME/sessions/` (default
`~/.grok/sessions/`). Set `GROK_BUILD_HOME` only when using a custom session
store. The wrapper resolves `GROK_HOME` automatically, so an agent can run:

```bash
python harnesses/grok-build/entrypoint.py list
python harnesses/grok-build/entrypoint.py sync
python harnesses/grok-build/entrypoint.py restore grok-build <session-id>
```
