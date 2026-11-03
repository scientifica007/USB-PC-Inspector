"""Regressions from HP 630 field sessions dated 2026-11-03."""
import copy
import unittest

from inspector.diagnostic_evidence import build_diagnostic_review, diagnostic_review_text


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.l1 = {"schema_version": 1,
                   "purchase_assessment": {"verdict": "do_not_buy"},
                   "health_assessment": {"overall": "critical"},
                   "storage": [{"smart": {"overall_passed": False}}]}

    def test_limited_cpu_ram_and_smart_rejection(self):
        original = copy.deepcopy(self.l1)
        sessions = [{"level": "L3", "status": "complete", "results": {
            "cpu": {"status": "pass_limited", "duration_seconds": 300.009},
            "memory": {"status": "pass_limited", "tested_mib": 64}}}]
        result = build_diagnostic_review(self.l1, sessions)
        self.assertEqual(result["purchase_verdict"], "do_not_buy")
        self.assertEqual(result["components"][0]["status"], "limited_pass")
        self.assertEqual(result["components"][1]["status"], "limited_pass")
        self.assertIn("64 MiB", diagnostic_review_text(result))
        self.assertEqual(self.l1, original)
        self.assertNotIn("diagnostic_review", self.l1)

    def test_legacy_attempts_not_a_health_pass(self):
        sessions = [{"level": "interactive", "results": {
            "screen": {"status": "user_review_required"},
            "camera": {"status": "preview_requested"},
            "speaker": {"status": "output_attempted"}}}]
        result = build_diagnostic_review(self.l1, sessions)
        statuses = {x["id"]: x["status"] for x in result["components"]}
        self.assertEqual(statuses["screen"], "needs_confirmation")
        self.assertEqual(statuses["camera"], "needs_confirmation")
        self.assertEqual(statuses["speaker"], "needs_confirmation")

    def test_explicit_user_fail_is_preserved(self):
        sessions = [{"level": "interactive",
                     "results": {"screen": {"status": "user_review_required"}},
                     "user_verdicts": {"screen": {"status": "fail",
                                                  "note": "الألوان لا تظهر"}}}]
        result = build_diagnostic_review(self.l1, sessions)
        self.assertEqual(result["components"][2]["status"], "reported_fail")
        self.assertIn("الألوان لا تظهر", diagnostic_review_text(result))

    def test_failed_probe_cannot_be_hidden_by_newer_pass(self):
        sessions = [
            {"level": "L3", "results": {"cpu": {"status": "stopped_heat"}}},
            {"level": "L3", "results": {"cpu": {"status": "pass_limited"}}},
        ]
        result = build_diagnostic_review(self.l1, sessions)
        self.assertEqual(result["components"][0]["status"], "probe_failed")


if __name__ == "__main__":
    unittest.main()
