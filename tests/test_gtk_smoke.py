"""GTK smoke tests. Full UI test requires xvfb-run and python3-gi."""
import os
import unittest

try:
    from inspector import gtk_gui
    from gi.repository import Gtk
except (ImportError, ValueError):
    gtk_gui = None
    Gtk = None


@unittest.skipUnless(gtk_gui is not None and bool(os.environ.get("DISPLAY")),
                     "GTK graphical test requires python3-gi and X display")
class GtkSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ok, _args = Gtk.init_check([])
        if not ok:
            raise unittest.SkipTest("GTK display initialization unavailable")

    def test_window_starts_pending_in_rtl_and_json_is_ltr(self):
        win = gtk_gui.InspectorWindow()
        try:
            self.assertEqual(win.get_direction(), Gtk.TextDirection.RTL)
            self.assertEqual(win.json_view.get_direction(), Gtk.TextDirection.LTR)
            self.assertIn("لا قرار", win.decision_title.get_text())
            self.assertFalse(win.save_button.get_sensitive())
            self.assertFalse(win.copy_button.get_sensitive())
        finally:
            win.destroy()

    def test_completed_report_renders_arabic_verdict(self):
        win = gtk_gui.InspectorWindow()
        try:
            data = {
                "bios": {"model": "HP 630"},
                "cpu": {"model": "Intel Core i3"},
                "memory": {"total_bytes": 8 * 1024**3},
                "storage": [{"model": "Hitachi HDD", "size_bytes": 500_000_000_000,
                             "smart": {"status": "partial", "overall_passed": False}}],
                "purchase_assessment": {
                    "verdict": "do_not_buy",
                    "reason": "مؤشر SMART يُبلّغ عن إخفاق.",
                },
                "findings": [{"level": "warning", "message": "قرص غير موثوق"}],
            }
            win._update_dashboard(
                gtk_gui.dashboard_model(data, complete=True)
            )
            self.assertEqual(win.decision_title.get_text(), "لا يُنصح بالشراء")
            self.assertIn("SMART", win.decision_reason.get_text())
            self.assertEqual(len(win.notes_box.get_children()), 1)
            self.assertEqual(win.fact_labels[2].get_text(), "8.0 GiB")
        finally:
            win.destroy()


if __name__ == "__main__":
    unittest.main()
