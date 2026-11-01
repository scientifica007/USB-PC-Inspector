"""P2 USB profile isolation tests; only temporary directories, never real USB."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inspector.p2_profiles import ProfileError
from inspector import profile_store


PROFILE = {
    "profile_schema_version": 1, "name": "برمجة وتصفح",
    "requirements": {"min_ram_gb": 16, "require_ssd": True},
    "max_price_dzd": 100000, "workloads": ["light_programming"]
}


class UsbProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch_root = patch.object(profile_store, "report_destination",
                                       return_value=self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def test_save_and_import_sha_readback_and_independent_sessions(self):
        reportdir = self.root / "PC-Inspector-Reports"
        reportdir.mkdir()
        marker = reportdir / "old-session.json"
        marker.write_bytes(b"preserve-this-previous-report")
        orig = deepcopy(PROFILE)
        first = profile_store.save_profile(PROFILE)
        second = profile_store.save_profile(PROFILE)
        self.assertNotEqual(first["filename"], second["filename"])
        self.assertEqual(first["verification"], "readback_sha256_and_fsync")
        self.assertEqual(PROFILE, orig)
        content = (self.root / profile_store.PROFILES_DIR /
                   first["filename"]).read_bytes()
        self.assertEqual(len(content), first["bytes"])
        self.assertEqual(hashlib.sha256(content).hexdigest(), first["sha256"])
        saved = profile_store.load_profile(first["filename"])
        self.assertEqual(saved["profile"], PROFILE)
        self.assertEqual(saved["sha256"], first["sha256"])
        listing = profile_store.list_profiles()
        self.assertEqual(len(listing), 2)
        self.assertEqual({x["filename"] for x in listing},
                         {first["filename"], second["filename"]})
        self.assertEqual(marker.read_bytes(), b"preserve-this-previous-report")

    def test_invalid_data_rejected_before_mount_attempt(self):
        with patch.object(profile_store, "report_destination",
                          side_effect=AssertionError("mount must not occur")):
            with self.assertRaises(ProfileError):
                profile_store.save_profile({"profile_schema_version": 1,
                                            "name": "A", "unknown": "bad"})
            with self.assertRaises(ProfileError):
                profile_store.load_profile("../../etc/shadow")

    def test_symlink_profile_is_never_followed(self):
        (self.root / profile_store.PROFILES_DIR).mkdir()
        target = self.root / "sensitive"
        target.write_text("secret", encoding="utf-8")
        link = self.root / profile_store.PROFILES_DIR / ("profile-" + "a"*32 + ".json")
        link.symlink_to(target)
        self.assertEqual(profile_store.list_profiles(), [])
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            profile_store.load_profile(link.name)
        self.assertEqual(target.read_text(encoding="utf-8"), "secret")

    def test_symlink_directory_is_never_followed(self):
        external = self.root / "external"
        external.mkdir()
        (self.root / profile_store.PROFILES_DIR).symlink_to(external)
        with self.assertRaises((OSError, RuntimeError)):
            profile_store.save_profile(PROFILE)
        self.assertEqual(list(external.iterdir()), [])

    def test_no_preexisting_profiles_is_not_failure(self):
        self.assertEqual(profile_store.list_profiles(), [])
        self.assertFalse((self.root / profile_store.PROFILES_DIR).exists())


if __name__ == "__main__":
    unittest.main()
