import unittest
from inspector.smart import decode_exit, interpret
from inspector.core import build_findings
from inspector.assessment import assess


class SmartBitmaskTests(unittest.TestCase):
    def test_zero_is_not_failure(self):
        self.assertEqual(decode_exit(0)["flags"], [])
        self.assertFalse(decode_exit(0)["critical"])

    def test_current_failure_bit(self):
        flags = decode_exit(8)
        self.assertTrue(flags["critical"])
        self.assertFalse(flags["historical"])

    def test_historical_error_log_is_not_current_failure(self):
        flags = decode_exit(64)
        self.assertFalse(flags["critical"])
        self.assertTrue(flags["historical"])

    def test_mixed_flags(self):
        flags = decode_exit(8 | 64 | 2)
        self.assertTrue(flags["critical"])
        self.assertTrue(flags["historical"])
        self.assertTrue(flags["read_failure"])

    def test_invalid_exit_code_is_unknown(self):
        self.assertFalse(decode_exit(-1)["known"])
        self.assertFalse(decode_exit(None)["known"])

    def test_evidence_and_privacy(self):
        data = {"smart_status": {"passed": True},
                "serial_number": "private-id",
                "ata_smart_error_log": {"summary": {"count": 2}}}
        result = interpret(data, 64)
        self.assertEqual(result["status"], "reported")
        self.assertIsNone(result["read_warning"])
        self.assertNotIn("serial_number", result["diagnostic_evidence"])
        self.assertEqual(result["diagnostic_evidence"]["ata_smart_error_log"]["summary"]["count"], 2)

    def test_historical_record_does_not_trigger_do_not_buy(self):
        smart = interpret({"smart_status": {"passed": True}}, 64)
        report = {"disk_probe_error": None,
                  "storage": [{"path": "/dev/sda", "smart": smart}], "battery": []}
        report["findings"] = build_findings(report)
        self.assertIn("smart_historical_errors", [f["code"] for f in report["findings"]])
        self.assertNotEqual(assess(report)["verdict"], "do_not_buy")

    def test_current_critical_exit_triggers_do_not_buy(self):
        smart = interpret({"smart_status": {"passed": True}}, 8)
        report = {"disk_probe_error": None,
                  "storage": [{"path": "/dev/sda", "smart": smart}], "battery": []}
        report["findings"] = build_findings(report)
        self.assertIn("smart_critical_exit", [f["code"] for f in report["findings"]])
        self.assertEqual(assess(report)["verdict"], "do_not_buy")


if __name__ == "__main__":
    unittest.main()
