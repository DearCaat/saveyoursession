import json
import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "hooks.json"


class HookCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads(HOOKS.read_text(encoding="utf-8"))
        cls.entries = data["hooks"]["SessionEnd"][0]["hooks"]

    def test_commands_are_fail_open_and_python3_only(self):
        commands = [entry["command"] for entry in self.entries]
        self.assertGreaterEqual(len(commands), 2)
        for command in commands:
            self.assertIn("command -v python3", command)
            self.assertIn("|| true", command)
            self.assertNotIn(" python \"", command)

    def test_codex_timeout_respects_three_second_cap(self):
        codex = next(entry for entry in self.entries if "sync_codex_session" in entry["command"])
        self.assertLessEqual(codex["timeout"], 3)

    def test_missing_root_does_not_expand_to_hooks_at_filesystem_root(self):
        codex = next(entry for entry in self.entries if "sync_codex_session" in entry["command"])
        env = os.environ.copy()
        env.pop("PLUGIN_ROOT", None)
        result = subprocess.run(
            ["/bin/sh", "-c", codex["command"]],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("/hooks/sync_codex_session.py", result.stderr)

    def test_missing_python3_is_non_blocking(self):
        claude = next(entry for entry in self.entries if "sync_claude_session" in entry["command"])
        env = {"PATH": "/nonexistent"}
        result = subprocess.run(
            ["/bin/sh", "-c", claude["command"]],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
