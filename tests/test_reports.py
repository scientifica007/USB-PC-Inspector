import unittest
from inspector.report import make_html
from inspector.usb_store import find_usb_partition, validate


class ReportTests(unittest.TestCase):
    def test_refuses_internal_partition_even_with_correct_label(self):
        tree = {"blockdevices": [
            {"type": "disk", "tran": "sata", "path": "/dev/sda",
             "children": [{"type": "part", "path": "/dev/sda1",
                           "label": "PCINSPECTOR_DATA", "fstype": "vfat"}]},
        ]}
        self.assertIsNone(find_usb_partition(tree))

    def test_usb_partition_selected_and_boot_partition_skipped(self):
        tree = {"blockdevices": [
            {"type": "disk", "tran": "usb", "path": "/dev/sdb", "children": [
                {"type": "part", "path": "/dev/sdb1",
                 "label": "Ventoy", "fstype": "exfat"},
                {"type": "part", "path": "/dev/sdb2",
                 "label": "VTOYEFI", "fstype": "vfat"},
            ]},
        ]}
        self.assertEqual(find_usb_partition(tree)["path"], "/dev/sdb1")

    def test_only_supported_schema(self):
        with self.assertRaises(ValueError):
            validate({"schema_version": 2})
        self.assertEqual(validate({"schema_version": 1, "storage": [],
                                   "bios": {}, "findings": []})["schema_version"], 1)

    def test_html_escapes_untrusted_firmware_strings(self):
        report = {"bios": {"model": "<script>alert(1)</script>"},
                  "cpu": {}, "memory": {}, "storage": [], "battery": [],
                  "findings": [{"level": "warning", "code": "x",
                                "message": "<img src=x onerror=alert(1)>"}]}
        content = make_html(report)
        self.assertNotIn("<script>", content)
        self.assertNotIn("<img src=x", content)
        self.assertIn("&lt;script&gt;", content)


if __name__ == "__main__":
    unittest.main()
