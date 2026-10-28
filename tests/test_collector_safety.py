"""Safe simulated collector checks: no writes, disks or mounts involved."""
import json
import unittest
from unittest.mock import patch
from inspector import core


class CollectorSafetyTests(unittest.TestCase):
    def test_l1_issues_only_read_operations_and_skips_usb_media(self):
        block_list = {"blockdevices": [
            {"type": "disk", "path": "/dev/sda", "tran": "sata",
             "model": "Test HDD", "size": 500_000_000_000,
             "rota": True, "rm": False},
            {"type": "disk", "path": "/dev/sdb", "tran": "usb",
             "model": "Ventoy", "size": 8_000_000_000,
             "rota": False, "rm": True},
        ]}
        seen = []
        def fake_run(argv, timeout=core.COMMAND_TIMEOUT):
            seen.append(tuple(argv))
            if argv[0] == "lsblk":
                return {"ok": True, "code": 0,
                        "stdout": json.dumps(block_list), "error": ""}
            if argv[0] == "smartctl":
                return {"ok": True, "code": 0,
                        "stdout": json.dumps({"smart_status": {"passed": True}}),
                        "error": ""}
            raise AssertionError("unexpected hardware command: " + repr(argv))

        with patch.object(core, "run_command", side_effect=fake_run), \
             patch.object(core, "bios_inventory", return_value={}), \
             patch.object(core, "cpu_inventory", return_value={}), \
             patch.object(core, "memory_inventory", return_value={}), \
             patch.object(core, "battery_inventory", return_value=[]), \
             patch.object(core.shutil, "which", return_value="/safe/tool"):
            result = core.collect()
        self.assertEqual(len(result["storage"]), 1)
        self.assertEqual(result["storage"][0]["path"], "/dev/sda")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0][0], "lsblk")
        self.assertEqual(seen[1], ("smartctl", "-a", "-j", "/dev/sda"))
        self.assertFalse(any("/dev/sdb" in part for args in seen for part in args))
        self.assertEqual(result["mode"], "observational_only")

    def test_memory_uses_observational_dmidecode_only(self):
        with patch.object(core, "read_text", return_value="MemTotal: 8192 kB"), \
             patch.object(core, "run_command", return_value={"ok": False,
                          "error": "no_dmi", "stdout": ""}) as run:
            result = core.memory_inventory()
        run.assert_called_once_with(["dmidecode", "--type", "17"])
        self.assertEqual(result["slots_status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
