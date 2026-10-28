"""Read-only report integrity and persistence acceptance regression tests."""
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from inspector.report_writer import REPORTS_DIR, store_verified_bundle
from scripts import verify_usb_reports as verify


class ReportVerificationTests(unittest.TestCase):
    FIRST = "pc-inspector-20261028T152139Z-d91e3a604cbc495b"
    SECOND = "pc-inspector-20261028T190610Z-7566a89bb84c46cf"

    def create_report(self, root, session, version):
        data = json.dumps({"schema_version": 1, "tool_version": version},
                          ensure_ascii=False).encode()
        return store_verified_bundle(
            root, session, data, b"<!doctype html><html></html>"
        )

    def test_two_complete_sessions_remain_valid_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_report(root, self.FIRST, "0.1.1-beta.1")
            self.create_report(root, self.SECOND, "0.1.2-beta.1")
            result = verify.verify_partition(
                root, min_sessions=2, required_sessions=(self.FIRST, self.SECOND)
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["checked"], 2)
            self.assertEqual({x["version"] for x in result["sessions"]},
                             {"0.1.1-beta.1", "0.1.2-beta.1"})

    def test_corrupted_json_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self.create_report(root, self.FIRST, "0.1.1-beta.1")
            Path(receipt["json"]).write_bytes(b'{"schema_version":2}')
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("mismatch" in msg
                                for msg in result["sessions"][0]["errors"]))

    def test_corrupted_html_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self.create_report(root, self.FIRST, "0.1.1-beta.1")
            Path(receipt["html"]).write_bytes(b"altered")
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertIn("SHA-256 mismatch: report.html",
                          result["sessions"][0]["errors"])

    def test_incomplete_bundle_never_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / REPORTS_DIR / self.FIRST
            session.mkdir(parents=True)
            (session / "report.json").write_text('{"schema_version": 1}')
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("complete.json" in e
                                for e in result["sessions"][0]["errors"]))

    def test_missing_previous_session_fails_preservation_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_report(root, self.SECOND, "0.1.2-beta.1")
            result = verify.verify_partition(
                root, required_sessions=(self.FIRST, self.SECOND)
            )
            self.assertFalse(result["ok"])
            self.assertTrue(any("missing preserved session" in issue
                                for issue in result["errors"]))

    def test_symlink_session_cannot_escape_reports_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_report(root, self.FIRST, "0.1.1-beta.1")
            (root / REPORTS_DIR / self.SECOND).symlink_to(
                root / REPORTS_DIR / self.FIRST, target_is_directory=True
            )
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("unsafe" in issue
                                for issue in result["sessions"][1]["errors"]))

    def test_symlink_reports_folder_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            (root / REPORTS_DIR).symlink_to(outside, target_is_directory=True)
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertTrue(any("unsafe" in issue for issue in result["errors"]))

    def test_readonly_verifier_never_uses_write_open_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.create_report(root, self.FIRST, "0.1.1-beta.1")
            actual_open = os.open
            observed = []
            def checked_open(path, flags, *args, **kwargs):
                observed.append(flags)
                return actual_open(path, flags, *args, **kwargs)
            with patch.object(verify.os, "open", side_effect=checked_open):
                result = verify.verify_partition(root)
            self.assertTrue(result["ok"], result)
            self.assertTrue(observed)
            self.assertTrue(all((flags & os.O_ACCMODE) == os.O_RDONLY and
                                not (flags & (os.O_CREAT | os.O_TRUNC | os.O_EXCL))
                                for flags in observed))

    def test_manifest_with_false_complete_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self.create_report(root, self.FIRST, "0.1.1-beta.1")
            manifest_path = Path(receipt["manifest"])
            data = json.loads(manifest_path.read_text())
            data["complete"] = False
            manifest_path.write_text(json.dumps(data))
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertIn("completion marker is not true",
                          result["sessions"][0]["errors"])

    def test_empty_partition_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / REPORTS_DIR).mkdir()
            result = verify.verify_partition(root)
            self.assertFalse(result["ok"])
            self.assertEqual(result["checked"], 0)


if __name__ == "__main__":
    unittest.main()
