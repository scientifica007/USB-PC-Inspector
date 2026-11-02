"""L2/L3 safety, bounded execution and evidence semantics."""
import threading
import unittest
from unittest.mock import patch

from inspector import diagnostics as diag


class Tests(unittest.TestCase):
    def test_invalid_level_never_executes(self):
        with self.assertRaises(ValueError):
            diag.run_level("L4")

    def test_ram_known_patterns(self):
        result = diag._ram(threading.Event(), 1)
        self.assertEqual(result["status"], "pass_limited")
        self.assertEqual(result["tested_mib"], 1)
        self.assertIn("لا يغطي", result["limitation"])

    def test_cancel_before_work(self):
        cancel = threading.Event()
        cancel.set()
        result = diag.run_level("L3", cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["results"], {})

    def test_l2_is_opt_in_and_manual_never_automatic_pass(self):
        emitted = []
        with patch.object(diag, "_peripheral_inventory", return_value={"status": "inventory_only"}):
            with patch.object(diag, "_temperature", return_value={"status": "unknown", "max_c": None}):
                result = diag.run_level("L2", emitted.append, cpu_seconds=0.05)
        self.assertEqual(result["level"], "L2")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["results"]["memory"]["status"], "pass_limited")
        self.assertEqual(len(emitted), 5)
        self.assertTrue(all(x["status"] == "not_tested" for x in result["manual_tests"]))
        self.assertNotIn("overall_health_percent", result)

    def test_long_run_denied_without_thermal_sensor(self):
        with patch.object(diag, "_temperature", return_value={"status": "unknown", "max_c": None}):
            result = diag._cpu(threading.Event(), seconds=120)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("الحرارة", result["reason"])

    def test_thermal_cutoff_stops_workload(self):
        with patch.object(diag, "_temperature", return_value={"max_c": 91.0}):
            result = diag._cpu(threading.Event(), seconds=3.0)
        self.assertEqual(result["status"], "stopped_heat")
        self.assertLess(result["iterations"], 40000)


if __name__ == "__main__":
    unittest.main()
