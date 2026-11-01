"""P2 reporting correctness: generic mode stability and safe custom HTML."""
from __future__ import annotations

from copy import deepcopy
import unittest

from inspector.p2_presentation import make_personal_snapshot, personal_text
from inspector.report import make_html


def report():
    return {
        "schema_version": 1, "tool_version": "0.1.6-beta.2",
        "bios": {"model": "HP 630"},
        "cpu": {"logical_processors": 4},
        "memory": {"slots_status": "reported", "slots": [{"size": "4 GB"},
                                                          {"size": "4 GB"}]},
        "storage": [{"size_bytes": 500107862016, "rotational": True,
                     "smart": {"overall_passed": False}}],
        "purchase_assessment": {"verdict": "do_not_buy", "reason": "SMART failing",
                                "limitations": ["Not certified"]},
        "health_assessment": {"overall": "critical"},
        "suitability_assessment": {"workloads": [{"id": "office",
                                                "verdict": "conditional"}]},
        "findings": []
    }


class P2PresentationTests(unittest.TestCase):
    def test_general_snapshot_is_unchanged(self):
        original = report()
        self.assertIs(make_personal_snapshot(original, None), original)
        self.assertNotIn("buyer_profile", original)
        self.assertNotIn("buyer_profile_assessment", original)
        self.assertIn("الوضع العام", personal_text(original, None))

    def test_custom_snapshot_is_detached_and_keeps_raw_evidence(self):
        raw = report()
        before = deepcopy(raw)
        profile = {"profile_schema_version": 1, "name": "مكتب",
                   "workloads": ["office"], "max_price_dzd": 65000}
        result = make_personal_snapshot(raw, profile, {"asking_price_dzd": 50000})
        self.assertEqual(raw, before)
        self.assertIsNot(result, raw)
        self.assertEqual(result["storage"], raw["storage"])
        self.assertEqual(result["purchase_assessment"]["verdict"], "do_not_buy")
        self.assertEqual(result["buyer_profile_assessment"]["personal_verdict"], "reject")
        self.assertEqual(result["buyer_offer"]["asking_price_dzd"], 50000)
        self.assertIn("لا يُنصح", personal_text(raw, profile))

    def test_html_escapes_seller_inputs_and_keeps_original_L1(self):
        raw = report()
        name = '<script>alert("x")</script>'
        profile = {"profile_schema_version": 1, "name": name,
                   "seller_claims": {"model": "<img src=x onerror=alert(1)>"}}
        enriched = make_personal_snapshot(raw, profile)
        rendered = make_html(enriched)
        self.assertIn("التقييم الشخصي وفق ملف المتطلبات", rendered)
        self.assertIn("خلاصة الفحص الأولي L1", rendered)
        self.assertNotIn(name, rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn('<img src=x onerror=alert(1)>', rendered)
        self.assertIn("الحكم العام L1 لا يتغير", rendered)
        self.assertNotIn("التقييم الشخصي وفق ملف المتطلبات", make_html(raw))


if __name__ == "__main__":
    unittest.main()
