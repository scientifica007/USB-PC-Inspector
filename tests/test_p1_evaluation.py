"""Offline, deterministic P1 rules: fixture tests without real hardware I/O."""
from __future__ import annotations

from copy import deepcopy
import unittest

from inspector.p1_evaluation import (
    RULE_VERSION, health_assessment, installed_ram_gb, suitability_assessment,
)
from inspector.ui_model import dashboard_model
from inspector.report import make_html


def hp_report() -> dict:
    return {
        "schema_version": 1, "tool_version": "0.1.6-beta.1",
        "bios": {"model": "HP 630"},
        "cpu": {"model": "Intel Core i3 M370", "logical_processors": 4},
        "memory": {
            "total_bytes": 8115171328, "slots_status": "reported",
            "slots": [{"size": "4 GB", "type": "DDR3"},
                      {"size": "4 GB", "type": "DDR3"}],
        },
        "storage": [{"path": "/dev/sda", "model": "Hitachi HDD",
                     "rotational": True,
                     "smart": {"status": "reported", "overall_passed": False,
                               "smartctl_exit": {"critical": True,
                                                 "read_failure": False}}}],
        "battery": [],
        "hardware_extensions": {
            "graphics": [{"description": "Intel Integrated Graphics",
                          "test_status": "not_tested"}],
            "displays": [{"connector": "card0-LVDS-1",
                          "connection_status": "connected",
                          "test_status": "not_tested"},
                         {"connector": "card0-HDMI-A-1",
                          "connection_status": "disconnected"}],
            "networks": [{"interface": "wlo1", "kind": "wifi",
                          "test_status": "not_tested"}],
        },
        "purchase_assessment": {
            "verdict": "do_not_buy", "reason": "SMART failed",
        },
        "findings": [{"code": "smart_failed", "level": "warning",
                      "message": "SMART"}],
    }


class P1EvaluationTests(unittest.TestCase):
    def test_observed_failure_is_critical_but_other_components_not_healthy(self):
        report = hp_report()
        before = deepcopy(report)
        result = health_assessment(report)
        self.assertEqual(result["rule_version"], RULE_VERSION)
        self.assertEqual(result["overall"], "critical")
        disk = [x for x in result["components"] if x["category"] == "storage"][0]
        self.assertEqual(disk["status"], "critical")
        for kind in ("cpu", "memory", "gpu", "display", "network"):
            items = [x for x in result["components"] if x["category"] == kind]
            self.assertTrue(items, kind)
            self.assertTrue(all(x["status"] == "not_tested" for x in items))
        self.assertEqual(
            [x for x in result["components"] if x["category"] == "battery"][0]["status"],
            "unknown",
        )
        self.assertEqual(report, before)

    def test_passed_smart_is_not_certificate_of_health(self):
        report = hp_report()
        report["storage"][0]["smart"] = {
            "status": "reported", "overall_passed": True}
        result = health_assessment(report)
        self.assertEqual(result["overall"], "unknown")
        disk = [x for x in result["components"] if x["category"] == "storage"][0]
        self.assertEqual(disk["status"], "limited")
        self.assertIn("لا يستبعد", disk["reason"])

    def test_no_disk_or_no_gpu_does_not_assert_absence(self):
        report = hp_report()
        report["storage"] = []
        report["hardware_extensions"] = {}
        result = health_assessment(report)
        self.assertEqual(result["overall"], "unknown")
        self.assertTrue(any(x["category"] == "gpu" and x["status"] == "unknown"
                            for x in result["components"]))
        self.assertTrue(any(x["category"] == "storage" and x["status"] == "unknown"
                            for x in result["components"]))

    def test_workloads_do_not_overrule_purchase_safety(self):
        report = hp_report()
        before = deepcopy(report)
        assessment = suitability_assessment(report)
        by_id = {x["id"]: x for x in assessment["workloads"]}
        self.assertEqual(by_id["office"]["verdict"], "conditional")
        self.assertEqual(by_id["light_programming"]["verdict"], "conditional")
        self.assertEqual(by_id["heavy_programming"]["verdict"], "unsuitable")
        self.assertEqual(by_id["video_1080p"]["verdict"], "unsuitable")
        self.assertEqual(by_id["modern_gaming"]["verdict"], "unsuitable")
        self.assertTrue(all(x["health_blocker"] for x in assessment["workloads"]))
        self.assertTrue(all(x["benchmark_tested"] is False for x in assessment["workloads"]))
        self.assertEqual(report["purchase_assessment"]["verdict"], "do_not_buy")
        self.assertEqual(report, before)

    def test_high_spec_gpu_dependant_workload_still_undetermined(self):
        report = hp_report()
        report["memory"]["slots"] = [{"size": "16 GB", "type": "DDR4"}]
        report["storage"][0]["smart"]["overall_passed"] = True
        report["storage"][0]["smart"]["smartctl_exit"]["critical"] = False
        assessment = suitability_assessment(report)
        by_id = {x["id"]: x for x in assessment["workloads"]}
        self.assertEqual(by_id["modern_gaming"]["verdict"], "undetermined")
        self.assertEqual(by_id["video_1080p"]["verdict"], "undetermined")
        self.assertFalse(by_id["modern_gaming"]["health_blocker"])

    def test_memory_unknown_never_uses_memtotal_to_invent_installed_capacity(self):
        report = hp_report()
        report["memory"]["slots_status"] = "unavailable"
        report["memory"]["slots"] = []
        self.assertIsNone(installed_ram_gb(report["memory"]))
        assessment = suitability_assessment(report)
        self.assertTrue(all(x["verdict"] == "undetermined"
                            for x in assessment["workloads"]))

    def test_mixed_modules_and_invalid_sizes(self):
        self.assertEqual(installed_ram_gb({
            "slots_status": "reported",
            "slots": [{"size": "4096 MB"}, {"size": "8 GB"}],
        }), 12)
        for bad in ("No Module Installed", "4 TB", "-8 GB", "999999 GB"):
            self.assertIsNone(installed_ram_gb({
                "slots_status": "reported", "slots": [{"size": bad}],
            }))

    def test_progress_and_old_reports_fail_closed(self):
        report = hp_report()
        report["health_assessment"] = health_assessment(report)
        report["suitability_assessment"] = suitability_assessment(report)
        model = dashboard_model(report, complete=False)
        self.assertNotIn("خلل حرج", model["health_panel"])
        self.assertIn("الفحص جارٍ", model["health_panel"])
        self.assertIn("بعد اكتمال الفحص", model["suitability_panel"])
        completed = dashboard_model(report, complete=True)
        self.assertIn("خلل حرج", completed["health_panel"])
        self.assertIn("الأعمال المكتبية", completed["suitability_panel"])
        legacy = dashboard_model({"schema_version": 1}, complete=True)
        self.assertIn("لم يُنجز", legacy["health_panel"])
        self.assertIn("لا تتوفر", legacy["suitability_panel"])

    def test_html_arabic_right_alignment_evidence_and_escaping(self):
        report = hp_report()
        report["health_assessment"] = health_assessment(report)
        report["suitability_assessment"] = suitability_assessment(report)
        report["cpu"]["model"] = "<script>x</script>"
        report["health_assessment"]["components"][0]["name"] = "<svg onload=x>"
        output = make_html(report)
        self.assertIn("direction:rtl;text-align:right", output)
        self.assertIn("الإصدار: 0.1.6-beta.1", output)
        self.assertIn("الحالة الصحية للمكونات", output)
        self.assertIn("ملاءمة الأعمال والاستخدامات", output)
        self.assertIn("خلل حرج مثبت", output)
        self.assertIn("مناسب بشروط", output)
        self.assertNotIn("<script>x</script>", output)
        self.assertIn("&lt;svg onload=x&gt;", output)

    def test_smart_read_warning_null_is_not_called_unknown_when_false(self):
        report = hp_report()
        output = make_html(report)
        self.assertIn("لا يوجد فشل قراءة مُبلَّغ عنه", output)


if __name__ == "__main__":
    unittest.main()
