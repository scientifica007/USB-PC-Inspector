"""Read-only import file tests for user-selected JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from inspector.p2_file_import import import_profile_file
from inspector.p2_profiles import ProfileError


class P2SelectedFileImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_valid_profile_import_from_regular_file(self):
        p = {"profile_schema_version": 1, "name": "اختيار شخصي",
             "requirements": {"min_ram_gb": 8}}
        path = self.root / "buyer.json"
        data = json.dumps(p, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        self.assertEqual(import_profile_file(str(path)), p)
        self.assertEqual(path.read_bytes(), data)

    def test_reject_symlink_fifo_and_invalid_data(self):
        good = self.root / "good.json"
        good.write_text('{"profile_schema_version":1,"name":"A"}')
        link = self.root / "alias.json"
        link.symlink_to(good)
        with self.assertRaises(OSError):
            import_profile_file(str(link))
        pipe = self.root / "pipe"
        os.mkfifo(pipe)
        with self.assertRaises(ProfileError):
            import_profile_file(str(pipe))
        with self.assertRaises(ProfileError):
            import_profile_file("relative.json")
        bad = self.root / "bad.json"
        bad.write_text('{"profile_schema_version":1,"name":"A","name":"B"}')
        with self.assertRaises(ProfileError):
            import_profile_file(str(bad))
        big = self.root / "big.json"
        big.write_bytes(b"x" * 65537)
        with self.assertRaises(ProfileError):
            import_profile_file(str(big))


if __name__ == "__main__":
    unittest.main()
