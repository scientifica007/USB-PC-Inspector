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
                 patch.object(usb_store.subprocess, "run", side_effect=failures) as call, \
                 patch.object(usb_store, "verified_mount") as verify:
                self.assertEqual(usb_store.mount_usb_data(partition), Path(work))
                verify.assert_called_once_with(partition, Path(work))
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


    def test_mounted_partition_source_mismatch_is_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as work:
            target = Path(work)
            candidate = {"path": "/dev/null", "fstype": "exfat", "label": "PCINSPDATA"}
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"filesystems": [
                    {"source": "/dev/zero", "target": str(target), "fstype": "exfat"}
                ]}),
            )
            with patch.object(usb_store.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "not the selected USB"):
                    usb_store.verified_mount(candidate, target)

    def test_mounted_partition_source_correct_is_accepted(self):
        import json
        with tempfile.TemporaryDirectory() as work:
            target = Path(work)
            candidate = {"path": "/dev/null", "fstype": "exfat", "label": "PCINSPDATA"}
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"filesystems": [
                    {"source": "/dev/null", "target": str(target), "fstype": "exfat"}
                ]}),
            )
            with patch.object(usb_store.subprocess, "run", return_value=result):
                usb_store.verified_mount(candidate, target)

    def test_mounted_partition_wrong_filesystem_is_rejected(self):
        import json
        with tempfile.TemporaryDirectory() as work:
            target = Path(work)
            candidate = {"path": "/dev/null", "fstype": "exfat", "label": "PCINSPDATA"}
            result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"filesystems": [
                    {"source": "/dev/null", "target": str(target), "fstype": "ext4"}
                ]}),
            )
            with patch.object(usb_store.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "filesystem type"):
                    usb_store.verified_mount(candidate, target)


    def test_pcinspector_partition_priority_rejects_internal_decoy(self):
        tree = {"blockdevices": [
            {"type": "disk", "tran": "sata", "children": [
                {"type": "part", "path": "/dev/sda2", "label": "PCINSPDATA",
                 "fstype": "vfat"}]},
            {"type": "disk", "tran": "usb", "children": [
                {"type": "part", "path": "/dev/sdb1", "label": "Ventoy",
                 "fstype": "exfat"},
                {"type": "part", "path": "/dev/sdb3", "label": "PCINSPDATA",
                 "fstype": "vfat"}]},
        ]}
        self.assertEqual(usb_store.find_usb_partition(tree)["path"], "/dev/sdb3")
        tree["blockdevices"][1]["tran"] = "sata"
        self.assertIsNone(usb_store.find_usb_partition(tree))

    def test_two_reports_in_single_process_keep_both_bundles_and_hashes(self):
        """Mock USB mount: two L1 reports saved sequentially, without real devices."""
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as work:
            first = {"schema_version": 1, "bios": {"model": "scan-one"},
                     "storage": [], "findings": []}
            second = {"schema_version": 1, "bios": {"model": "scan-two"},
                      "storage": [], "findings": []}
            with patch.object(usb_store, "report_destination", return_value=Path(work)), \
                 patch.object(usb_store, "make_html",
                              side_effect=lambda r: "<html>" + r["bios"]["model"] + "</html>"):
                receipt_a = usb_store.save(first)
                original_json = Path(receipt_a["json"]).read_bytes()
                original_html = Path(receipt_a["html"]).read_bytes()
                receipt_b = usb_store.save(second)
            self.assertTrue(receipt_a["saved"] and receipt_b["saved"])
            self.assertNotEqual(Path(receipt_a["json"]).parent,
                                Path(receipt_b["json"]).parent)
            self.assertEqual(Path(receipt_a["json"]).read_bytes(), original_json)
            self.assertEqual(Path(receipt_a["html"]).read_bytes(), original_html)
            self.assertEqual(json.loads(Path(receipt_b["json"]).read_bytes())
                             ["bios"]["model"], "scan-two")
            self.assertEqual(len(list((Path(work) / "PC-Inspector-Reports").iterdir())), 2)
            for receipt in (receipt_a, receipt_b):
                manifest = json.loads(Path(receipt["manifest"]).read_text())
                self.assertIs(manifest["complete"], True)
                for name, key in (("report.json", "json"), ("report.html", "html")):
                    payload = Path(receipt[key]).read_bytes()
                    self.assertEqual(len(payload), manifest["files"][name]["bytes"])
                    self.assertEqual(hashlib.sha256(payload).hexdigest(),
                                     manifest["files"][name]["sha256"])

if __name__ == "__main__":
    unittest.main()
