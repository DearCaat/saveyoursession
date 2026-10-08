import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import server


SID = "5d2eadec-046f-44b1-9850-81433a8ddaac"
SRC_A = "11111111-aaaa-4bbb-8ccc-000000000001"
SRC_B = "22222222-aaaa-4bbb-8ccc-000000000002"


class FetchTests(unittest.TestCase):
    def test_fetch_downloads_single_remote_session(self):
        prefix = f"v1/{SRC_A}/claude/{SID}/loc1"
        listing = [f"{prefix}/{SID}.jsonl", f"{prefix}/metadata.json", "v1/%s/claude/other/loc2/other.jsonl" % SRC_A]

        def fake_download(remote_prefix, staging):
            self.assertEqual(remote_prefix, prefix)
            (Path(staging) / f"{SID}.jsonl").write_text("transcript")
            (Path(staging) / "metadata.json").write_text("{}")

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(server, "_remote_listing", return_value=listing), \
                patch.object(server, "_download_session", side_effect=fake_download):
            result = server.fetch("claude", SID, str(Path(tmp) / "out"))
            self.assertEqual(sorted(Path(p).name for p in result["fetched"]), [f"{SID}.jsonl", "metadata.json"])
            self.assertEqual((Path(tmp) / "out" / f"{SID}.jsonl").read_text(), "transcript")
            self.assertEqual(result["skipped_existing"], [])

    def test_fetch_refuses_ambiguous_sources_until_locator_is_given(self):
        listing = [f"v1/{SRC_A}/claude/{SID}/locA/{SID}.jsonl", f"v1/{SRC_B}/claude/{SID}/locB/{SID}.jsonl"]
        with patch.object(server, "_remote_listing", return_value=listing), \
                patch.object(server, "_download_session") as download:
            with self.assertRaisesRegex(ValueError, "locator-hash"):
                server.fetch("claude", SID, "/tmp/unused-fetch-dest")
            download.assert_not_called()

    def test_fetch_missing_session_is_an_error(self):
        with patch.object(server, "_remote_listing", return_value=[]):
            with self.assertRaisesRegex(ValueError, "no remote session"):
                server.fetch("claude", SID, "/tmp/unused-fetch-dest")

    def test_fetch_never_overwrites_existing_file(self):
        prefix = f"v1/{SRC_A}/claude/{SID}/loc1"

        def fake_download(remote_prefix, staging):
            (Path(staging) / f"{SID}.jsonl").write_text("remote")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            dest.mkdir()
            (dest / f"{SID}.jsonl").write_text("local")
            with patch.object(server, "_remote_listing", return_value=[f"{prefix}/{SID}.jsonl"]), \
                    patch.object(server, "_download_session", side_effect=fake_download):
                result = server.fetch("claude", SID, str(dest))
            self.assertEqual(result["fetched"], [])
            self.assertEqual((dest / f"{SID}.jsonl").read_text(), "local")


class RemoteListingTests(unittest.TestCase):
    def test_listing_keeps_object_paths_from_agent_rows(self):
        stdout = (
            "  521061  2026-09-01 10:14:02  v1/src/claude/sid/loc/sid.jsonl\n"
            "  158  2026-09-01 10:18:09  v1/src/claude/sid/loc/metadata.json\n"
            "\n"
        )
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="Hint: ignored\n")
        with patch.object(server, "_hf_settings", return_value=("hf://buckets/Dearcat/agent-session", "repo", "tok")), \
                patch.object(server.subprocess, "run", return_value=done) as run:
            paths = server._remote_listing("v1")
        self.assertEqual(paths, ["v1/src/claude/sid/loc/sid.jsonl", "v1/src/claude/sid/loc/metadata.json"])
        self.assertIn("hf://buckets/Dearcat/agent-session/v1", run.call_args.args[0])


class SummaryTests(unittest.TestCase):
    def test_summary_is_uploaded_under_fixed_name_beside_session(self):
        captured = {}

        def fake_upload(path, remote_prefix):
            captured["name"] = Path(path).name
            captured["text"] = Path(path).read_text()
            captured["prefix"] = remote_prefix
            return {"uploaded": True}

        prefix = f"v1/{SRC_A}/claude/{SID}/loc1"
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "my-notes.md"
            source.write_text("# summary")
            with patch.object(server, "_upload_hf", side_effect=fake_upload):
                result = server._upload_summary(str(source), prefix)
        self.assertEqual(captured, {"name": "SUMMARY.md", "text": "# summary", "prefix": prefix})
        self.assertEqual(result["remote_path"], f"{prefix}/SUMMARY.md")
        self.assertTrue(result["uploaded"])

    def test_sync_summary_needs_a_session_id_before_any_work(self):
        with patch.object(server, "discover") as discover:
            with self.assertRaisesRegex(ValueError, "needs --session-id"):
                server.sync("claude", None, None, "/tmp/some-summary.md")
            discover.assert_not_called()

    def test_sync_summary_rejects_missing_file_before_any_work(self):
        with patch.object(server, "discover") as discover:
            with self.assertRaisesRegex(ValueError, "summary file not found"):
                server.sync("claude", SID, None, "/nonexistent/summary.md")
            discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
