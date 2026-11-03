"""Regression: L1 verdict, derived evidence, and safe standalone phone HTML."""
import unittest

from inspector.p2_presentation import make_personal_snapshot
from inspector.report import make_html


class IntegrationTests(unittest.TestCase):
    def test_deep_results_are_escaped_without_changing_l1(self):
        report = {
            "schema_version": 1, "tool_version": "0.2.0-beta.1",
            "bios": {"model": "HP 630"}, "cpu": {"model": "i3"},
            "memory": {"total_bytes": 8192}, "battery": [], "storage": [],
            "findings": [{"level": "warning", "code": "smart_failed", "message": "SMART failed"}],
            "purchase_assessment": {
                "verdict": "do_not_buy", "reason": "SMART failure",
                "limitations": ["User has not verified CPU/RAM health"],
            },
            "diagnostic_sessions": [{
                "level": "L2", "status": "complete",
                "results": {"<script>alert(1)</script>": {
                    "status": "pass_limited", "limitation": "محاولة فحص محدودة"}},
                "limitations": "not certified",
            }],
        }
        output = make_html(report)
        self.assertIn("L2 / L3", output)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", output)
        self.assertNotIn("<script>alert(1)</script>", output)
        self.assertIn("SMART failure", output)
        self.assertEqual(report["purchase_assessment"]["verdict"], "do_not_buy")

    def test_human_review_is_html_escaped(self):
        from inspector.diagnostic_evidence import build_diagnostic_review
        report = {"schema_version": 1, "tool_version": "0.2.1-beta.1",
                  "bios": {"model": "HP630"},
                  "purchase_assessment": {"verdict": "do_not_buy"}}
        sessions = [{"level": "interactive",
                     "results": {"screen": {"status": "user_review_required"}},
                     "user_verdicts": {"screen": {"status": "fail",
                                                 "note": "<script>bad()</script>"}}}]
        report["diagnostic_sessions"] = sessions
        report["diagnostic_review"] = build_diagnostic_review(report, sessions)
        html = make_html(report)
        self.assertIn("سُجلت مشكلة", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)

    def test_general_mode_without_profile_preserves_raw(self):
        raw = {"schema_version": 1, "purchase_assessment": {"verdict": "do_not_buy"}}
        self.assertIs(make_personal_snapshot(raw, None), raw)


if __name__ == "__main__":
    unittest.main()
