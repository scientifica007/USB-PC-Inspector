import unittest
from unittest.mock import patch
from inspector import core


class CoreTests(unittest.TestCase):
    def test_no_internal_disk_is_not_a_crash(self):
        lsblk = {"blockdevices": [
            {"type": "disk", "tran": "usb", "path": "/dev/sdb", "size": 16000000000}
        ]}
        with patch.object(core, "parse_json_command", return_value=(lsblk, None)):
            disks, error = core.list_internal_disks()
        self.assertEqual(disks, [])
        self.assertIsNone(error)
        report = {"storage": disks, "disk_probe_error": error, "battery": []}
        findings = core.build_findings(report)
        self.assertEqual(findings[0]["code"], "no_internal_disk_detected")

    def test_unknown_disk_scan_is_not_reported_as_absence(self):
        findings = core.build_findings({
            "storage": [], "disk_probe_error": "tool_unavailable", "battery": [],
        })
        self.assertEqual(findings[0]["level"], "unknown")
        self.assertEqual(findings[0]["code"], "disk_scan_unavailable")

    def test_smartctl_partial_json(self):
        sample = {"smart_status": {"passed": False},
                  "power_on_time": {"hours": 4826},
                  "nvme_smart_health_information_log": {"percentage_used": 82}}
        with patch.object(core, "parse_json_command",
                          return_value=(sample, "nonzero_exit")):
            result = core.smart_summary("/dev/nvme0n1")
        self.assertEqual(result["status"], "partial")
        self.assertFalse(result["overall_passed"])
        self.assertEqual(result["power_on_hours"], 4826)

    def test_reject_unusual_device_path(self):
        with patch.object(core, "parse_json_command") as call:
            result = core.smart_summary("/dev/../../tmp/test")
        self.assertEqual(result["status"], "not_tested")
        call.assert_not_called()

    def test_warning_classification(self):
        report = {
            "disk_probe_error": None,
            "storage": [{"path": "/dev/sda", "smart": {
                "status": "reported", "overall_passed": False,
                "power_on_hours": 4200, "nvme_percentage_used": 95,
            }}],
            "battery": [{"estimated_health_percent": 60}],
        }
        codes = [x["code"] for x in core.build_findings(report)]
        self.assertIn("smart_failed", codes)
        self.assertIn("drive_hours", codes)
        self.assertIn("nvme_wear", codes)
        self.assertIn("battery_wear", codes)


if __name__ == "__main__":
    unittest.main()
