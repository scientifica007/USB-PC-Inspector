import unittest
from inspector.assessment import assess


class AssessmentTests(unittest.TestCase):
    def base(self, smart):
        return {"storage": [{"path": "/dev/sda", "smart": smart}],
                "disk_probe_error": None, "findings": []}

    def test_missing_smart_is_undetermined(self):
        self.assertEqual(assess(self.base({"status": "unavailable"}))["verdict"], "undetermined")

    def test_missing_disk_is_undetermined(self):
        self.assertEqual(assess({"storage": [], "disk_probe_error": None, "findings": []})["verdict"], "undetermined")

    def test_smart_failure_blocks_purchase(self):
        report = self.base({"status": "reported", "overall_passed": False})
        report["findings"] = [{"code": "smart_failed", "level": "warning"}]
        self.assertEqual(assess(report)["verdict"], "do_not_buy")

    def test_warning_requires_inspection(self):
        report = self.base({"status": "reported"})
        report["findings"] = [{"code": "battery_wear", "level": "warning"}]
        self.assertEqual(assess(report)["verdict"], "inspect_before_payment")

    def test_no_warnings_is_not_certification(self):
        result = assess(self.base({"status": "reported", "overall_passed": True}))
        self.assertEqual(result["verdict"], "inspect_before_payment")
        self.assertFalse(result["price_assessed"])


    def test_complete_inventory_can_be_provisional_candidate(self):
        report = self.base({"status": "reported", "overall_passed": True})
        report["bios"] = {"model": "Example"}
        report["cpu"] = {"model": "Example CPU"}
        report["memory"] = {"total_bytes": 8 * 1024**3}
        verdict = assess(report)
        self.assertEqual(verdict["verdict"], "candidate")
        self.assertFalse(verdict["price_assessed"])
        self.assertIn("مبدئيًا", verdict["reason"])

    def test_candidate_requires_clean_current_smart_result(self):
        report = self.base({"status": "partial", "overall_passed": True})
        report["bios"] = {"model": "Example"}
        report["cpu"] = {"model": "Example CPU"}
        report["memory"] = {"total_bytes": 8 * 1024**3}
        self.assertNotEqual(assess(report)["verdict"], "candidate")


if __name__ == "__main__":
    unittest.main()
