"""GTK smoke tests. Full UI test requires xvfb-run and python3-gi."""
import os
import unittest
from unittest.mock import patch

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
            self.assertEqual(win.json_view.get_justification(), Gtk.Justification.LEFT)
            for view in (win.hardware_view, win.health_view, win.suitability_view):
                self.assertEqual(view.get_direction(), Gtk.TextDirection.RTL)
                self.assertEqual(view.get_justification(), Gtk.Justification.LEFT)
            self.assertEqual(win.decision_reason.get_xalign(), 0.0)
            self.assertEqual(win.decision_reason.get_justify(), Gtk.Justification.LEFT)
            self.assertEqual(win.fact_labels[0].get_xalign(), 0.0)
            # GtkLabel:xalign is mirrored in RTL. 0.0 is physical RIGHT.
            self.assertIn("لا قرار", win.decision_title.get_text())
            self.assertFalse(win.save_button.get_sensitive())
            self.assertFalse(win.copy_button.get_sensitive())
        finally:
            win.destroy()

    def test_mixed_arabic_english_paragraphs_share_rtl_base(self):
        raw = "اسم القطعة: Intel CPU\n    الحالة: لم تُختبر\nGPU 8086:0046\n"
        result = gtk_gui.rtl_paragraphs(raw)
        lines = result.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(line.startswith("\u200f") for line in lines[:3]))
        self.assertTrue(lines[1].endswith("الحالة: لم تُختبر"))
        self.assertEqual(lines[3], "")
        self.assertNotIn("\u200f", raw)

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
            self.assertIn("8.0 GiB", win.fact_labels[2].get_text())
            self.assertIn("المركبة", win.fact_titles[2].get_text())
            self.assertIn("لم يُنجز", win.health_view.get_buffer().get_text(
                win.health_view.get_buffer().get_start_iter(),
                win.health_view.get_buffer().get_end_iter(), True))
            self.assertIn("لا تتوفر", win.suitability_view.get_buffer().get_text(
                win.suitability_view.get_buffer().get_start_iter(),
                win.suitability_view.get_buffer().get_end_iter(), True))
        finally:
            win.destroy()

    def test_memory_card_shows_installed_and_kernel_amounts(self):
        win = gtk_gui.InspectorWindow()
        try:
            data = {"memory": {
                "total_bytes": 8115175424, "slots_status": "reported",
                "slots": [{"size": "4 GB", "type": "DDR3"},
                          {"size": "4 GB", "type": "DDR3"}]}}
            win._update_dashboard(gtk_gui.dashboard_model(data))
            self.assertIn("المركبة", win.fact_titles[2].get_text())
            self.assertIn("2 × 4 GB DDR3", win.fact_labels[2].get_text())
            self.assertIn("7.6 GiB", win.fact_labels[2].get_text())
        finally:
            win.destroy()

    def test_save_failure_preserves_report_and_retry_button(self):
        win = gtk_gui.InspectorWindow()
        try:
            report = {"schema_version": 1, "bios": {"model": "demo"}}
            win.report = report
            win.saving = True
            win.save_button.set_sensitive(False)
            with patch.object(win, "_dialog") as alert:
                win._receive("save_error", "no writable USB partition")
            self.assertIs(win.report, report)
            self.assertFalse(win.saving)
            self.assertTrue(win.save_button.get_sensitive())
            self.assertTrue(win.scan_button.get_sensitive())
            self.assertIn("الذاكرة", win.status.get_text())
            alert.assert_called_once()
        finally:
            win.destroy()


if __name__ == "__main__":
    unittest.main()
