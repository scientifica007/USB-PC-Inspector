import unittest
from inspector.report import make_html
from inspector.usb_store import find_usb_partition, validate


class ReportTests(unittest.TestCase):
    def test_refuses_internal_partition_even_with_correct_label(self):
        tree = {"blockdevices": [
            {"type": "disk", "tran": "sata", "path": "/dev/sda",
             "children": [{"type": "part", "path": "/dev/sda1",
                           "label": "PCINSPDATA", "fstype": "vfat"}]},
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

    def test_html_localizes_bios_date_without_mutating_json(self):
        source = {"bios": {"bios_date": "12/13/2011"}, "cpu": {}, "memory": {},
                  "storage": [], "battery": [], "findings": []}
        html = make_html(source)
        self.assertIn("13/12/2011", html)
        self.assertNotIn("12/13/2011", html)
        self.assertEqual(source["bios"]["bios_date"], "12/13/2011")

    def test_html_shows_verdict_and_collapses_smart_details(self):
        report = {"created_utc": "2026-10-29T17:01:22+00:00",
                  "bios": {"model": "HP 630", "bios_date": "12/13/2011"},
                  "cpu": {"model": "i3 M370"},
                  "memory": {"total_bytes": 8115175424, "slots_status": "reported",
                             "slots": [{"size": "4 GB", "type": "DDR3"},
                                       {"size": "4 GB", "type": "DDR3"}]},
                  "storage": [{"path": "/dev/sda", "model": "Hitachi",
                               "smart": {"status": "reported",
                                         "overall_passed": False,
                                         "diagnostic_evidence": {"ata_smart_error_log":
                                                                 {"summary": {"count": 4851}}}}}],
                  "battery": [],
                  "findings": [{"code": "smart_failed", "level": "warning",
                                "message": "فشل SMART"}],
                  "purchase_assessment": {"verdict": "do_not_buy", "reason": "قرص غير موثوق",
                                          "limitations": ["لا يشمل السعر أو الضمان."]},
                  "scan_timing": {"total_seconds": 1.867}}
        import copy
        original = copy.deepcopy(report)
        result = make_html(report)
        self.assertIn("لا يُنصح بالشراء", result)
        self.assertIn("قرص غير موثوق", result)
        self.assertIn("smart_failed", result)
        self.assertIn("8 GB (2 × 4 GB DDR3)", result)
        self.assertIn("7.6 GiB", result)
        self.assertIn("13/12/2011", result)
        self.assertIn("تفاصيل SMART الفنية (حقول مختارة)", result)
        self.assertIn("4851", result)
        self.assertIn("لا يشمل السعر أو الضمان.", result)
        self.assertEqual(report, original)

    def test_html_without_assessment_is_undetermined(self):
        result = make_html({"bios": {}, "cpu": {}, "memory": {},
                            "storage": [], "battery": [], "findings": []})
        self.assertIn("النتيجة غير محسومة", result)
        self.assertIn("لا توجد أدلة تشخيصية", result)
        self.assertIn("لم تُعرض أقراص داخلية", result)

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
