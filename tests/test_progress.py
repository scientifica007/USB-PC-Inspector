"""Offline tests for progressive L1 events; no real hardware is probed."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

from inspector import core


class ProgressiveScanTests(unittest.TestCase):
    def test_stages_and_final_report_use_single_scan(self):
        events = []
        fake_disks = [{"path": "/dev/sda", "model": "Test disk",
                       "size_bytes": 1000000, "transport": "sata"}]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(core, "bios_inventory",
                                            return_value={"manufacturer": "Test"}))
            stack.enter_context(patch.object(core, "cpu_inventory",
                                            return_value={"model": "CPU"}))
            stack.enter_context(patch.object(core, "memory_inventory",
                                            return_value={"total_bytes": 8 * 1024**3}))
            stack.enter_context(patch.object(core, "battery_inventory", return_value=[]))
            stack.enter_context(patch.object(core, "list_internal_disks",
                                            return_value=(fake_disks, None)))
            smart = stack.enter_context(patch.object(core, "smart_summary",
                                                   return_value={"status": "reported",
                                                                 "overall_passed": True}))
            report = core.collect(progress=events.append)
        self.assertEqual([e["stage"] for e in events],
                         ["identity", "memory", "battery", "storage", "smart"])
        self.assertEqual(smart.call_count, 1)
        self.assertTrue(all(e["type"] == "progress" for e in events))
        self.assertTrue(all("purchase_assessment" not in e["snapshot"] for e in events))
        self.assertIsNone(events[3]["snapshot"]["storage"][0]["smart"])
        self.assertEqual(events[-1]["snapshot"]["storage"][0]["smart"]["status"],
                         "reported")
        self.assertEqual(report["storage"][0]["smart"]["status"], "reported")
        self.assertIn("purchase_assessment", report)
        self.assertGreaterEqual(report["scan_timing"]["total_seconds"], 0)
        self.assertIn("storage", report["scan_timing"]["stage_seconds"])

    def test_no_internal_disk_is_reported_without_smart(self):
        events = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(core, "bios_inventory", return_value={}))
            stack.enter_context(patch.object(core, "cpu_inventory", return_value={}))
            stack.enter_context(patch.object(core, "memory_inventory", return_value={}))
            stack.enter_context(patch.object(core, "battery_inventory", return_value=[]))
            stack.enter_context(patch.object(core, "list_internal_disks",
                                            return_value=([], None)))
            smart = stack.enter_context(patch.object(core, "smart_summary"))
            report = core.collect(progress=events.append)
        smart.assert_not_called()
        self.assertEqual(events[-1]["stage"], "storage")
        self.assertEqual(report["purchase_assessment"]["verdict"], "undetermined")

    def test_stream_mode_emits_parseable_final_json(self):
        def fake_collect(progress=None):
            progress({"type": "progress", "stage": "identity", "snapshot": {}})
            return {"schema_version": 1, "purchase_assessment": {"verdict": "undetermined"}}
        output = io.StringIO()
        with patch.object(core, "collect", side_effect=fake_collect), \
             patch.object(sys, "argv", ["inspector.core", "--events"]), \
             contextlib.redirect_stdout(output):
            core.main()
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([event["type"] for event in messages],
                         ["progress", "complete"])
        self.assertEqual(messages[-1]["report"]["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
