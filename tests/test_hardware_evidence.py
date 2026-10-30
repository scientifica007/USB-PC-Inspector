"""P0 collectors: fixture-based tests, never probe live hardware or write disks."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from inspector import hardware_evidence as hw
from inspector.ui_model import extended_hardware_text
from inspector.report import make_html


class HardwareEvidenceTests(unittest.TestCase):
    def test_pci_graphics_read_only_and_unknown_human_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gpu = root / "0000:00:02.0"
            gpu.mkdir()
            (gpu / "class").write_text("0x030000\n")
            (gpu / "vendor").write_text("0x8086\n")
            (gpu / "device").write_text("0x0046\n")
            other = root / "0000:00:1f.2"
            other.mkdir()
            (other / "class").write_text("0x010601\n")
            with patch.object(hw, "pci_names", return_value={
                    "0000:00:02.0": "Intel Corporation Integrated Graphics [8086:0046]"}):
                found = hw.graphics_inventory(root)
            self.assertEqual(len(found), 1)
            self.assertIn("Intel", found[0]["description"])
            self.assertEqual(found[0]["vendor_id"], "0x8086")
            self.assertEqual(found[0]["test_status"], "not_tested")
            self.assertNotIn("serial", found[0])

    def test_display_edid_date_is_panel_date_only(self):
        edid = bytearray(128)
        edid[:8] = bytes.fromhex("00ffffffffffff00")
        edid[16] = 21
        edid[17] = 34   # 2024
        self.assertEqual(hw.edid_manufacture_date(bytes(edid)), {"week": 21, "year": 2024})
        edid[16] = 0
        self.assertIsNone(hw.edid_manufacture_date(bytes(edid)))
        self.assertIsNone(hw.edid_manufacture_date(b"not an edid"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            connected = root / "card0-eDP-1"
            connected.mkdir()
            (connected / "status").write_text("connected\n")
            (connected / "modes").write_text("1366x768\n")
            (connected / "edid").write_bytes(bytes(edid[:16]) + bytes([21, 34]) + bytes(110))
            results = hw.display_inventory(root)
            self.assertEqual(results[0]["reported_modes"], ["1366x768"])
            self.assertEqual(results[0]["panel_manufacture_date"]["year"], 2024)
            self.assertNotIn("edid_raw", results[0])

    def test_network_no_mac_or_ip_in_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wlan = root / "wlan0"
            wlan.mkdir()
            (wlan / "device").mkdir()
            (wlan / "wireless").mkdir()
            (wlan / "address").write_text("aa:bb:cc:dd:ee:ff")
            (wlan / "operstate").write_text("up")
            loop = root / "lo"
            loop.mkdir()
            result = hw.network_inventory(root)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["kind"], "wifi")
            self.assertNotIn("address", result[0])
            self.assertNotIn("aa:bb:cc:dd:ee:ff", str(result))

    def test_hours_belong_to_disk_not_computer_age(self):
        report = {
            "bios": {"bios_date": "12/13/2011"},
            "storage": [{"path": "/dev/sda", "smart": {"power_on_hours": 40728}},
                        {"path": "/dev/nvme0n1", "smart": {"power_on_hours": None}}],
            "hardware_extensions": {"displays": []},
        }
        data = hw.age_evidence(report)
        self.assertEqual([item["kind"] for item in data],
                         ["firmware_date", "powered_hours"])
        self.assertEqual(data[1]["value"], 40728)
        self.assertIn("ليست العمر", data[1]["limitations"])
        self.assertFalse(any(item.get("kind") == "computer_age" for item in data))

    def test_html_and_gtk_explain_evidence_and_missing_data(self):
        report = {
            "bios": {"model": "HP 630"},
            "cpu": {"model": "i3"},
            "memory": {},
            "storage": [],
            "findings": [],
            "battery": [],
            "hardware_extensions": {
                "graphics": [{"description": "<script>alert(1)</script>",
                              "vendor_id": "0x8086", "device_id": "0x0046"}],
                "displays": [],
                "networks": [{"interface": "wlan0", "kind": "wifi"}],
            },
            "age_evidence": [
                {"kind": "powered_hours", "path": "/dev/sda", "value": 40728,
                 "source": "smartctl", "limitations": "ساعات القرص لا تعني عمر الجهاز"}
            ],
        }
        human = extended_hardware_text(report)
        self.assertIn("40", human)
        self.assertIn("لم يُختبر", human)
        self.assertIn("ساعات تشغيل القرص", human)
        html = make_html(report)
        self.assertIn("المكونات الإضافية", html)
        self.assertIn("العمر وساعات التشغيل", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_missing_evidence_never_invents_age_or_health(self):
        self.assertIn("غير متاح", extended_hardware_text({}))
        self.assertEqual(hw.age_evidence({"storage": []}), [])


if __name__ == "__main__":
    unittest.main()
