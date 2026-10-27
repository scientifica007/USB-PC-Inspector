"""No real USB hardware needed: persistence, rollback, symlink and hash tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inspector import report_writer as writer


class ReportWriterTests(unittest.TestCase):
    SESSION = "pc-inspector-20261027T193000Z-abcdef1234567890"

    def test_write_verify_and_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            mount = Path(root)
            payload = b'{"schema_version":1}\n'
            html = b"<html>inspection</html>"
            receipt = writer.store_verified_bundle(mount, self.SESSION, payload, html)
            self.assertTrue(receipt["saved"])
            self.assertEqual(Path(receipt["json"]).read_bytes(), payload)
            self.assertEqual(Path(receipt["html"]).read_bytes(), html)
            manifest = json.loads(Path(receipt["manifest"]).read_text())
            self.assertTrue(manifest["complete"])
            self.assertEqual(manifest["files"]["report.json"]["sha256"],
                             hashlib.sha256(payload).hexdigest())
            self.assertEqual(manifest["files"]["report.html"]["sha256"],
                             hashlib.sha256(html).hexdigest())

    def test_second_scan_does_not_replace_first(self):
        with tempfile.TemporaryDirectory() as root:
            mount = Path(root)
            original = writer.store_verified_bundle(
                mount, self.SESSION, b"first", b"<html>first</html>"
            )
            with self.assertRaises(FileExistsError):
                writer.store_verified_bundle(
                    mount, self.SESSION, b"overwrite", b"<html>overwrite</html>"
                )
            next_session = "pc-inspector-20261027T193005Z-ffffffffffffffff"
            second = writer.store_verified_bundle(
                mount, next_session, b"second", b"<html>second</html>"
            )
            self.assertEqual(Path(original["json"]).read_bytes(), b"first")
            self.assertEqual(Path(second["json"]).read_bytes(), b"second")

    def test_symlink_to_other_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            mount = Path(root) / "mount"
            other = Path(root) / "other"
            mount.mkdir()
            other.mkdir()
            (mount / writer.REPORTS_DIR).symlink_to(other, target_is_directory=True)
            with self.assertRaises(OSError):
                writer.store_verified_bundle(
                    mount, self.SESSION, b"data", b"<html></html>"
                )
            self.assertEqual(list(other.iterdir()), [])

    def test_incomplete_write_does_not_publish_complete_marker(self):
        with tempfile.TemporaryDirectory() as root:
            mount = Path(root)
            real_write = writer._write_verified
            def fail_second(fd, name, payload):
                if name == "report.html":
                    raise OSError("simulated USB failure")
                return real_write(fd, name, payload)
            with patch.object(writer, "_write_verified", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "simulated USB failure"):
                    writer.store_verified_bundle(
                        mount, self.SESSION, b"json", b"html"
                    )
            session = mount / writer.REPORTS_DIR / self.SESSION
            self.assertEqual((session / "report.json").read_bytes(), b"json")
            self.assertFalse((session / "complete.json").exists())

    def test_no_space_no_write(self):
        with tempfile.TemporaryDirectory() as root:
            fake = type("StatVfs", (), {"f_bavail": 0, "f_frsize": 4096})()
            with patch.object(writer.os, "statvfs", return_value=fake):
                with self.assertRaisesRegex(RuntimeError, "Insufficient free space"):
                    writer.store_verified_bundle(
                        Path(root), self.SESSION, b"json", b"html"
                    )
            self.assertFalse((Path(root) / writer.REPORTS_DIR).exists())

    def test_session_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                writer.store_verified_bundle(
                    Path(root), "../danger", b"json", b"html"
                )
            self.assertFalse((Path(root) / writer.REPORTS_DIR).exists())

    def test_failure_when_base_mount_is_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            mount = Path(root) / "mount"
            mount.mkdir()
            alias = Path(root) / "alias"
            alias.symlink_to(mount, target_is_directory=True)
            with self.assertRaises(OSError):
                writer.store_verified_bundle(alias, self.SESSION, b"json", b"html")
            self.assertEqual(list(mount.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
