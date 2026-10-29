"""Pure L1 dashboard tests: errors, unknowns and interim states."""
import unittest

from inspector.ui_model import (
    dashboard_model, date_ar, memory_text, memory_summary, disk_text, smart_text, short,
)


class DashboardModelTests(unittest.TestCase):
    def fixture(self):
        return {
            "created_utc": "2026-10-28T15:17:04+00:00",
            "bios": {"manufacturer": "Hewlett-Packard", "model": "HP 630"},
            "cpu": {"model": "Intel Core i3 M370"},
            "memory": {"total_bytes": 8 * (1024 ** 3)},
            "battery": [],
            "storage": [{"model": "Hitachi HDD", "size_bytes": 500_000_000_000,
                         "smart": {"status": "partial", "overall_passed": False}}],
            "purchase_assessment": {"verdict": "do_not_buy",
                                    "reason": "قرص التخزين أبلغ عن إخفاق SMART."},
            "findings": [{"level": "warning", "code": "smart_failed",
                          "message": "القرص أبلغ عن إخفاق في تقييم SMART."}],
            "scan_timing": {"total_seconds": 2.18},
        }

    def test_interim_never_shows_purchase_recommendation(self):
        model = dashboard_model(self.fixture(), stage="smart", elapsed=1.4)
        self.assertFalse(model["complete"])
        self.assertEqual(model["tone"], "pending")
        self.assertIn("لا قرار", model["label"])
        self.assertNotIn("لا يُنصح بالشراء", model["label"])
        self.assertEqual(model["notes"], [])
        self.assertIn("SMART", model["state"])

    def test_complete_critical_verdict_has_explanation(self):
        model = dashboard_model(self.fixture(), complete=True)
        self.assertEqual(model["tone"], "danger")
        self.assertEqual(model["label"], "لا يُنصح بالشراء")
        self.assertIn("SMART", model["reason"])
        self.assertIn("إخفاق", dict(model["facts"])["SMART"])
        self.assertIn("2.18", model["timing"])

    def test_unavailable_smart_not_healthy(self):
        data = self.fixture()
        data["storage"][0]["smart"] = {"status": "unavailable"}
        self.assertEqual(smart_text(data["storage"]), "غير متاح")

    def test_no_disk_does_not_claim_health(self):
        data = self.fixture()
        data["storage"] = []
        data["purchase_assessment"]["verdict"] = "undetermined"
        model = dashboard_model(data, complete=True)
        self.assertEqual(model["tone"], "neutral")
        self.assertIn("لم يُكتشف", dict(model["facts"])["التخزين الداخلي"])

    def test_unknown_verdict_fails_closed(self):
        data = self.fixture()
        data["purchase_assessment"]["verdict"] = "unrecognized"
        model = dashboard_model(data, complete=True)
        self.assertEqual(model["tone"], "neutral")
        self.assertIn("غير محسومة", model["label"])

    def test_missing_report_is_safe(self):
        model = dashboard_model(None)
        self.assertEqual(model["tone"], "pending")
        self.assertEqual(dict(model["facts"])["المعالج"], "غير متاح")

    def test_dates_day_month_year(self):
        self.assertEqual(date_ar("2026-10-28T15:17:04+00:00"), "28/10/2026 15:17 UTC")
        self.assertEqual(date_ar("garbled"), "غير متاح")

    def test_ram_and_storage_units(self):
        self.assertEqual(memory_text(8 * 1024 ** 3), "8.0 GiB")
        self.assertEqual(memory_text(None), "غير متاح")
        self.assertIn("500 GB", disk_text(self.fixture()["storage"]))

    def test_installed_ram_is_not_kernel_memtotal(self):
        memory = {"total_bytes": 8115175424, "slots_status": "reported",
                  "slots": [{"size": "4 GB", "type": "DDR3"},
                            {"size": "4 GB", "type": "DDR3"}]}
        summary = memory_summary(memory)
        self.assertEqual(summary["installed"], "8 GB (2 × 4 GB DDR3)")
        self.assertEqual(summary["visible"], "7.6 GiB")
        model = dashboard_model({"memory": memory})
        title, value = model["facts"][2]
        self.assertIn("المركبة", title)
        self.assertIn("8 GB (2 × 4 GB DDR3)", value)
        self.assertIn("7.6 GiB", value)

    def test_unavailable_dmi_never_infers_installed_capacity(self):
        memory = {"total_bytes": 8 * 1024**3, "slots_status": "unavailable",
                  "slots": []}
        self.assertEqual(memory_summary(memory)["installed"], "غير متاح")
        memory["slots_status"] = "reported"
        memory["slots"] = [{"size": "4 GB"}, {"size": "No Module Installed"}]
        self.assertEqual(memory_summary(memory)["installed"], "غير متاح")

    def test_mixed_dmi_capacity_is_summed_without_guessing(self):
        memory = {"total_bytes": None, "slots_status": "reported",
                  "slots": [{"size": "4096 MB", "type": "DDR3"},
                            {"size": "8 GB", "type": "DDR4"}]}
        summary = memory_summary(memory)
        self.assertEqual(summary["installed"], "12 GB (4 GB + 8 GB)")
        self.assertEqual(summary["visible"], "غير متاح")

    def test_clean_status_does_not_prove_health(self):
        self.assertEqual(smart_text([{"smart": {"overall_passed": True,
                                                "status": "reported"}}]),
                         "لم يُبلّغ عن إخفاق حالي")

    def test_firmware_text_is_bounded_and_controls_removed(self):
        self.assertEqual(short("A\nB"), "A B")
        self.assertLessEqual(len(short("z" * 500)), 121)

    def test_limited_permissions_labeled(self):
        self.assertIn("محدودة", dashboard_model(
            self.fixture(), complete=True, reduced=True
        )["state"])

    def test_empty_battery_is_not_claimed_absent(self):
        self.assertEqual(dict(dashboard_model(
            self.fixture(), complete=True
        )["facts"])["البطارية"], "لا توجد بيانات بطارية")

    def test_report_reason_is_not_derived_from_interim_smart(self):
        data = self.fixture()
        interim = dashboard_model(data, complete=False)
        self.assertNotIn("إخفاق SMART", interim["reason"])


if __name__ == "__main__":
    unittest.main()
