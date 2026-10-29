"""Regressions for distinguishing SMART diagnostic failures and read failures."""
import unittest

from inspector.smart import interpret
from inspector.core import build_findings
from inspector.assessment import assess


class SmartEvidenceRegressionTests(unittest.TestCase):
    def report_for(self, data, code):
        smart = interpret(data, code)
        report = {
            "storage": [{"path": "/dev/sda", "smart": smart}],
            "disk_probe_error": None,
            "battery": [],
        }
        report["findings"] = build_findings(report)
        return smart, report, assess(report)

    def test_critical_disk_failure_is_readable(self):
        smart, report, decision = self.report_for(
            {"smart_status": {"passed": False}}, 88
        )
        self.assertEqual(smart["status"], "reported")
        self.assertIsNone(smart["read_warning"])
        self.assertTrue(smart["smartctl_exit"]["critical"])
        self.assertFalse(smart["smartctl_exit"]["read_failure"])
        self.assertEqual(decision["verdict"], "do_not_buy")
        self.assertNotIn("smart_read_incomplete",
                         [item["code"] for item in report["findings"]])

    def test_log_only_is_not_a_read_error(self):
        smart, report, decision = self.report_for(
            {"smart_status": {"passed": True}}, 64
        )
        self.assertEqual(smart["status"], "reported")
        self.assertNotEqual(decision["verdict"], "do_not_buy")

    def test_unavailable_smart_verdict_remains_incomplete(self):
        smart, report, decision = self.report_for({}, 0)
        self.assertEqual(smart["status"], "partial")
        self.assertIn("smart_read_incomplete",
                      [item["code"] for item in report["findings"]])
        self.assertEqual(decision["verdict"], "undetermined")

    def test_command_error_with_valid_failure_evidence_is_partial(self):
        smart, report, decision = self.report_for(
            {"smart_status": {"passed": False}}, 1 | 8
        )
        self.assertEqual(smart["status"], "partial")
        self.assertTrue(smart["smartctl_exit"]["read_failure"])
        self.assertEqual(decision["verdict"], "do_not_buy")


if __name__ == "__main__":
    unittest.main()
