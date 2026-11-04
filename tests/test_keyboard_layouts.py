"""Test reversible X11 layout selection without touching the real keyboard."""
import unittest
from unittest.mock import patch

from inspector import keyboard_layouts as k


class KeyboardLayoutTests(unittest.TestCase):
    def test_algerian_arabic_is_xkb_dz_ar(self):
        self.assertEqual(k.LAYOUTS["dz_ar"][1:3], ("dz", "ar"))
        self.assertEqual(k.LAYOUTS["fr"][1:3], ("fr", ""))
        self.assertEqual(k.LAYOUTS["us"][1:3], ("us", ""))

    def test_parse_restore_preserves_layout_model_and_options(self):
        original = k.parse_xkb_query(
            "rules: evdev\nmodel: pc105\nlayout: us,fr\nvariant: ,oss\n"
            "options: grp:alt_shift_toggle\n")
        self.assertEqual(original["layout"], "us,fr")
        self.assertEqual(
            k.xkb_arguments(original["layout"], original["variant"],
                            original["options"], original["model"]),
            ["setxkbmap", "-layout", "us,fr", "-variant", ",oss",
             "-option", "", "-model", "pc105",
             "-option", "grp:alt_shift_toggle"])

    def test_invalid_query_rejected(self):
        with self.assertRaises(ValueError):
            k.parse_xkb_query("layout: $(rm -rf /)\n")
        with self.assertRaises(ValueError):
            k.apply_test_layout("not_a_layout")

    def test_apply_layout_uses_argument_array(self):
        original = "model: pc105\nlayout: us\nvariant: \noptions: grp:alt_shift_toggle"
        with patch.dict("os.environ", {"DISPLAY": ":9",
                                       "XDG_SESSION_TYPE": "x11"}, clear=True):
            with patch("shutil.which", return_value="/usr/bin/setxkbmap"):
                with patch.object(k, "_run", side_effect=[original, ""]) as runner:
                    snapshot = k.apply_test_layout("dz_ar")
        self.assertEqual(snapshot["layout"], "us")
        args = runner.call_args_list[1].args[0]
        self.assertEqual(args[args.index("-layout") + 1], "dz")
        self.assertEqual(args[args.index("-variant") + 1], "ar")

    def test_wayland_fails_closed(self):
        with patch.dict("os.environ", {"DISPLAY": ":0",
                                        "XDG_SESSION_TYPE": "wayland"}, clear=True):
            with self.assertRaises(RuntimeError):
                k.read_x11_layout()

    def test_restoration_only_after_apply(self):
        original = {"layout": "fr", "model": "pc105",
                    "variant": "", "options": ""}
        with patch.object(k, "_run") as runner:
            k.restore_x11_layout(original)
            self.assertIn("fr", runner.call_args.args[0])
        with patch.object(k, "_run") as runner:
            k.restore_x11_layout(None)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
