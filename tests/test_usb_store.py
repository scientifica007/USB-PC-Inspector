"""USB writer safety and Ventoy alias regression coverage; no mounts executed."""
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from inspector import usb_store


class USBStoreTests(unittest.TestCase):
    def test_only_confirmed_usb_data_partitions(self):
        tree = {"blockdevices": [
            {"type": "disk", "tran": "sata", "children": [
                {"type": "part", "path": "/dev/sda1", "label": "PCINSPDATA",
                 "fstype": "exfat"}]},
            {"type": "disk", "tran": "usb", "children": [
                {"type": "part", "path": "/dev/sdb1", "label": "Ventoy",
                 "fstype": "exfat"}]},
        ]}
        self.assertEqual(usb_store.find_usb_partition(tree)["path"], "/dev/sdb1")

    def test_rejects_invalid_mapper_parent(self):
        self.assertIsNone(
            usb_store.validated_ventoy_mapper("/dev/../../root", mapper=Path("/missing"))
        )

    def test_accepts_mapper_only_if_single_slave_matches_usb(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            dev = root / "dev"
            sys_block = root / "sys"
            dev.mkdir()
            (dev / "dm-2").write_bytes(b"")
            mapper = root / "VentoyPart"
            mapper.symlink_to(dev / "dm-2")
            slaves = sys_block / "dm-2" / "slaves"
            slaves.mkdir(parents=True)
            (slaves / "sdb1").touch()
            with patch.object(usb_store.stat, "S_ISBLK", return_value=True):
                self.assertEqual(usb_store.validated_ventoy_mapper(
                    "/dev/sdb1", mapper=mapper, sys_block=sys_block), str(mapper))
                self.assertIsNone(usb_store.validated_ventoy_mapper(
                    "/dev/sda1", mapper=mapper, sys_block=sys_block))
                (slaves / "sda1").touch()
                self.assertIsNone(usb_store.validated_ventoy_mapper(
                    "/dev/sdb1", mapper=mapper, sys_block=sys_block))

    def test_retry_alias_after_physical_partition_is_busy(self):
        with tempfile.TemporaryDirectory() as work:
            partition = {"path": "/dev/sdb1", "label": "Ventoy"}
            failures = [
                SimpleNamespace(returncode=32, stderr="device busy", stdout=""),
                SimpleNamespace(returncode=0, stderr="", stdout=""),
            ]
            with patch.object(usb_store, "MOUNT_DIR", Path(work)), \
                 patch.object(usb_store, "validated_ventoy_mapper",
                              return_value="/dev/mapper/VentoyPart"), \
                 patch.object(usb_store.subprocess, "run", side_effect=failures) as call:
                self.assertEqual(usb_store.mount_usb_data(partition), Path(work))
            self.assertEqual(call.call_count, 2)
            self.assertEqual(call.call_args_list[0].args[0][-2], "/dev/sdb1")
            self.assertEqual(call.call_args_list[1].args[0][-2],
                             "/dev/mapper/VentoyPart")
            self.assertTrue(all("-o" in c.args[0] for c in call.call_args_list))

    def test_does_not_mount_unverified_alias(self):
        with tempfile.TemporaryDirectory() as work:
            partition = {"path": "/dev/sdb1", "label": "Ventoy"}
            with patch.object(usb_store, "MOUNT_DIR", Path(work)), \
                 patch.object(usb_store, "validated_ventoy_mapper",
                              return_value=None), \
                 patch.object(usb_store.subprocess, "run",
                              return_value=SimpleNamespace(
                                  returncode=32, stderr="device busy", stdout=""
                              )) as call:
                with self.assertRaisesRegex(RuntimeError, "device busy"):
                    usb_store.mount_usb_data(partition)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[0][-2], "/dev/sdb1")

    def test_existing_read_only_mount_is_rejected(self):
        partition = {"path": "/dev/sdb1", "label": "Ventoy",
                     "mountpoint": "/media/ventoy"}
        with patch.object(usb_store, "discover", return_value=partition), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(os, "statvfs", return_value=SimpleNamespace(
                 f_flag=os.ST_RDONLY
             )), \
             patch.object(usb_store, "mount_usb_data") as mount:
            with self.assertRaisesRegex(RuntimeError, "mounted read-only"):
                usb_store.report_destination()
            mount.assert_not_called()


if __name__ == "__main__":
    unittest.main()
