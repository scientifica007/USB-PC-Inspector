"""Deterministic P2 core tests; no hardware probing, disk writes or network."""
from __future__ import annotations

from copy import deepcopy
import unittest

from inspector.p2_profiles import (
    ProfileError, dump_profile_json, evaluate_purchase_profile,
    load_profile_json, validate_offer, validate_profile,
)


def sample_report():
    return {
        "bios": {"model": "HP 630"},
        "cpu": {"logical_processors": 4},
        "memory": {"total_bytes": 8115175424, "slots_status": "reported",
                   "slots": [{"size": "4 GB"}, {"size": "4 GB"}]},
        "storage": [{"size_bytes": 500107862016, "rotational": True}],
        "purchase_assessment": {"verdict": "do_not_buy"},
        "health_assessment": {"overall": "critical"},
        "suitability_assessment": {"workloads": [
            {"id": "office", "verdict": "conditional"},
            {"id": "heavy_programming", "verdict": "unsuitable"}]},
    }


class P2ProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "profile_schema_version": 1,
            "name": "البرمجة اليومية",
            "workloads": ["office"],
            "requirements": {"min_ram_gb": 8, "min_logical_processors": 4,
                             "require_ssd": True},
            "max_price_dzd": 50_000,
            "min_warranty_months": 6,
            "seller_claims": {"model": "HP 630", "ram_gb": 8},
        }

    def test_valid_profile_roundtrip_without_mutating_source(self):
        p = deepcopy(self.profile)
        self.assertEqual(load_profile_json(dump_profile_json(p)), p)
        self.assertEqual(p, self.profile)

    def test_strict_version_type_unknown_fields_and_workloads(self):
        invalid = [
            {"profile_schema_version": True, "name": "bad"},
            {"profile_schema_version": 99, "name": "bad"},
            {"profile_schema_version": 1, "name": ""},
            {**self.profile, "run_command": "shell"},
            {**self.profile, "requirements": {"min_ram_gb": True}},
            {**self.profile, "requirements": {"require_ssd": 1}},
            {**self.profile, "workloads": ["office", "office"]},
            {**self.profile, "workloads": ["not_a_workload"]},
            {**self.profile, "max_price_dzd": 1000.5},
        ]
        for entry in invalid:
            with self.subTest(entry=entry), self.assertRaises(ProfileError):
                validate_profile(entry)

    def test_import_rejects_duplicate_keys_nonfinite_and_oversize(self):
        for payload in (
            '{"profile_schema_version":1,"name":"a","name":"b"}',
            '{"profile_schema_version":1,"name":"a","max_price_dzd":NaN}',
            '{"profile_schema_version":1,"name":"a","max_price_dzd":Infinity}',
            '{"profile_schema_version":1,"name":"a","workloads":["invalid"]}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ProfileError):
                load_profile_json(payload)
        with self.assertRaises(ProfileError):
            load_profile_json(b"\xff")
        with self.assertRaises(ProfileError):
            load_profile_json(b" " * 65537)
        with self.assertRaises(ProfileError):
            validate_offer({"asking_price_dzd": False})
        with self.assertRaises(ProfileError):
            validate_offer({"warranty_months": -1})
        with self.assertRaises(ProfileError):
            validate_offer({"shell": "ls"})

    def test_general_mode_untouched(self):
        report = sample_report()
        original = deepcopy(report)
        result = evaluate_purchase_profile(report)
        self.assertEqual(result["mode"], "general")
        self.assertEqual(result["generic_verdict"], "do_not_buy")
        self.assertEqual(result["personal_verdict"], "not_applied")
        self.assertEqual(report, original)

    def test_bad_smart_is_hard_block_even_when_price_is_low(self):
        report = sample_report()
        original = deepcopy(report)
        p = deepcopy(self.profile)
        result = evaluate_purchase_profile(report, p,
                                           {"asking_price_dzd": 1000,
                                            "warranty_months": 24})
        self.assertEqual(result["axes"]["technical_safety"]["status"], "fail")
        self.assertEqual(result["personal_verdict"], "reject")
        self.assertEqual(result["generic_verdict"], "do_not_buy")
        self.assertEqual(report, original)
        self.assertEqual(p, self.profile)

    def test_hdd_and_overbudget_are_independent_failures(self):
        report = sample_report()
        report["health_assessment"]["overall"] = "unknown"
        report["purchase_assessment"]["verdict"] = "inspect_before_payment"
        result = evaluate_purchase_profile(report, self.profile,
                                           {"asking_price_dzd": 70_000,
                                            "warranty_months": 12})
        self.assertEqual(result["axes"]["hardware_requirements"]["status"], "fail")
        self.assertEqual(result["axes"]["economics"]["status"], "fail")
        self.assertEqual(result["axes"]["seller_claims"]["status"], "pass")
        self.assertEqual(result["axes"]["workload_fit"]["status"], "conditional")

    def test_missing_evidence_is_not_zero_or_pass(self):
        report = {"memory": {"total_bytes": 8000000000}, "storage": [],
                  "purchase_assessment": {"verdict": "undetermined"}}
        result = evaluate_purchase_profile(report, self.profile)
        self.assertEqual(result["axes"]["hardware_requirements"]["status"],
                         "needs_verification")
        self.assertEqual(result["axes"]["seller_claims"]["status"],
                         "needs_verification")
        self.assertEqual(result["axes"]["economics"]["status"],
                         "needs_verification")
        self.assertEqual(result["personal_verdict"], "inspect_before_payment")

    def test_profile_changes_capacity_judgment_not_observed_data(self):
        report = sample_report()
        report["health_assessment"]["overall"] = "unknown"
        report["purchase_assessment"]["verdict"] = "inspect_before_payment"
        snap = deepcopy(report)
        office = {"profile_schema_version": 1, "name": "office",
                  "workloads": ["office"]}
        heavy = {"profile_schema_version": 1, "name": "heavy",
                 "workloads": ["heavy_programming"]}
        result1 = evaluate_purchase_profile(report, office)
        result2 = evaluate_purchase_profile(report, heavy)
        self.assertEqual(result1["axes"]["workload_fit"]["status"], "conditional")
        self.assertEqual(result2["axes"]["workload_fit"]["status"], "fail")
        self.assertEqual(report, snap)


if __name__ == "__main__":
    unittest.main()
