import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import server


class CleanupControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.native = root / "native"
        self.native.mkdir()
        self.native_file = self.native / "session.txt"
        self.native_file.write_text("user: build the index\n", encoding="utf-8")
        self.patches = [
            patch.object(server, "ROOT", root / "state"),
            patch.object(server, "METADATA", root / "state" / "metadata"),
            patch.object(server, "INDEX", root / "state" / "index.json"),
            patch.object(server, "SOURCE", root / "state" / "source.json"),
            patch.object(server, "CONTROL", root / "state" / "control.json"),
            patch.object(server, "HARNESS_ROOTS", {"dsh": [self.native]}),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self._cleanup_patches)

    def _cleanup_patches(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_discovery_marks_unindexed_then_sync_indexed(self):
        found = server.discover("dsh")
        self.assertEqual(len(found), 1)
        parts = found[0]["session_key"].split(":")
        self.assertEqual(parts[0], "v1")
        self.assertEqual(parts[1], found[0]["source_id"])
        self.assertEqual(parts[2:4], ["dsh", "session"])
        self.assertEqual(parts[4], found[0]["locator_hash"])
        self.assertEqual(found[0]["index_status"], "discovered-unindexed")
        self.assertFalse(found[0]["indexed"])

        with patch.object(server, "_upload_hf", return_value={"uploaded": True}):
            result = server.sync("dsh")
        self.assertEqual(result["sessions"], 1)
        found = server.discover("dsh")
        self.assertEqual(found[0]["index_status"], "indexed")
        self.assertTrue(found[0]["indexed"])

    def test_cleanup_fingerprint_gate_and_live_change_detection(self):
        with patch.object(server, "_upload_hf", return_value={"uploaded": True}):
            server.sync("dsh")
        key = next(iter(server._load()["sessions"]))
        tagged = server.tag_cleanup(key, "terra dry-run candidate")
        self.assertEqual(tagged["status"], "tagged")
        self.assertTrue(tagged["fingerprint"])

        tagged_at = datetime.fromisoformat(tagged["cleanup_tagged_at"])
        before = server.cleanup_gate(key, now=tagged_at + timedelta(hours=71, minutes=59))
        self.assertFalse(before["allowed"])
        after = server.cleanup_gate(key, now=tagged_at + timedelta(hours=72))
        self.assertTrue(after["allowed"])

        self.native_file.write_text("user: changed after tag\n", encoding="utf-8")
        changed = server.cleanup_gate(key, now=tagged_at + timedelta(hours=73))
        self.assertFalse(changed["allowed"])
        self.assertEqual(changed["status"], "re-review")
        persisted = json.loads(server.CONTROL.read_text(encoding="utf-8"))
        self.assertEqual(persisted["cleanup"][key]["status"], "re-review")


if __name__ == "__main__":
    unittest.main()
