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


    def test_optional_buyer_tab_is_rtl_and_general_mode_is_unmodified(self):
        win = gtk_gui.InspectorWindow()
        try:
            self.assertIsNone(win.profile_panel.profile)
            self.assertEqual(win.profile_panel.result.get_direction(),
                             Gtk.TextDirection.RTL)
            self.assertEqual(win.profile_panel.result.get_justification(),
                             Gtk.Justification.LEFT)
            self.assertEqual(win.stack.get_child_by_name("buyer").get_direction(),
                             Gtk.TextDirection.RTL)
            raw = {"schema_version": 1, "bios": {"model": "HP 630"},
                   "purchase_assessment": {"verdict": "do_not_buy"}}
            win.report = raw
            self.assertIs(win._report_with_personal_context(), raw)
            self.assertNotIn("buyer_profile_assessment", raw)
        finally:
            win.destroy()

    def test_custom_profile_applies_without_changing_SMART_or_raw_json(self):
        win = gtk_gui.InspectorWindow()
        try:
            raw = {
                "schema_version": 1,
                "bios": {"model": "HP 630"},
                "cpu": {"logical_processors": 4},
                "memory": {"slots_status": "reported",
                           "slots": [{"size": "4 GB"}, {"size": "4 GB"}]},
                "storage": [{"size_bytes": 500107862016, "rotational": True}],
                "purchase_assessment": {"verdict": "do_not_buy"},
                "health_assessment": {"overall": "critical"},
                "suitability_assessment": {"workloads": []},
            }
            win.report = raw
            win.profile_panel.set_report(raw)
            win.profile_panel.custom_mode.set_active(True)
            win.profile_panel.fields["name"].set_text("مكتبي")
            win.profile_panel.fields["min_ram_gb"].set_text("8")
            win.profile_panel.apply()
            snapshot = win._report_with_personal_context()
            self.assertIsNot(snapshot, raw)
            self.assertEqual(snapshot["purchase_assessment"], raw["purchase_assessment"])
            self.assertEqual(snapshot["buyer_profile_assessment"]["personal_verdict"],
                             "reject")
            self.assertNotIn("buyer_profile_assessment", raw)
            win.profile_panel.general_mode.set_active(True)
            self.assertIs(win._report_with_personal_context(), raw)
        finally:
            win.destroy()



    def test_v020_optional_levels_and_phone_off_at_start(self):
        win = gtk_gui.InspectorWindow()
        try:
            self.assertEqual(win.sidebar.get_direction(), Gtk.TextDirection.RTL)
            self.assertIsNotNone(win.stack.get_child_by_name("diagnostics"))
            self.assertIsNotNone(win.stack.get_child_by_name("phone"))
            self.assertEqual(win.phone_panel.url, "")
            self.assertIsNone(win.phone_panel.bridge)
            self.assertFalse(win.diagnostics_panel.sessions)
            self.assertFalse(win.diagnostics_panel.stop_button.get_sensitive())
            win.diagnostics_panel.start_level("L2")
            self.assertIn("أكمل L1", win.diagnostics_panel.status.get_text())
        finally:
            win.destroy()

    def test_l2_health_summary_updates_without_changing_original_smart_verdict(self):
        win = gtk_gui.InspectorWindow()
        try:
            raw = {"schema_version": 1,
                   "cpu": {"model": "i3"}, "memory": {"total_bytes": 8192},
                   "purchase_assessment": {"verdict": "do_not_buy", "reason": "SMART failed"},
                   "health_assessment": {"overall": "critical"}}
            win.report = raw
            win._update_dashboard(gtk_gui.dashboard_model(raw, complete=True))
            win.diagnostics_panel.sessions.append({
                "level": "L3", "status": "complete",
                "results": {"cpu": {"status": "pass_limited", "duration_seconds": 120},
                            "memory": {"status": "pass_limited", "tested_mib": 64}}})
            win._on_diagnostic_complete()
            content = win.health_view.get_buffer().get_text(
                win.health_view.get_buffer().get_start_iter(),
                win.health_view.get_buffer().get_end_iter(), True)
            self.assertIn("اجتاز اختبارًا محدودًا", content)
            self.assertIn("تقييم L1 الأساسي", content)
            self.assertEqual(win._report_with_personal_context()["diagnostic_review"]["session_count"], 1)
            self.assertNotIn("diagnostic_review", raw)
            self.assertEqual(raw["purchase_assessment"]["verdict"], "do_not_buy")
        finally:
            win.destroy()

    def test_explicit_human_component_feedback_and_escape_capture(self):
        from types import SimpleNamespace
        from gi.repository import Gdk
        from inspector.interactive_gtk_tests import ComponentCheckWindow
        captured = []
        win = ComponentCheckWindow(captured.append)
        try:
            self.assertEqual(win._reviews["screen"][0].get_active_id(), "not_tested")
            win._reviews["screen"][0].set_active_id("fail")
            win._reviews["screen"][1].set_text("الألوان غير ظاهرة")
            win.show_all()
            win.notebook.set_current_page(1)
            self.assertEqual(win.notebook.get_current_page(), 1)
            win._keypress(win, SimpleNamespace(keyval=Gdk.KEY_Escape))
            self.assertIn(Gdk.KEY_Escape, win._keys)
            win._finish()
            self.assertEqual(captured[0]["user_verdicts"]["screen"]["status"], "fail")
            self.assertIn("Escape", win.key_label.get_text())
        finally:
            if win.get_visible():
                win.destroy()

    def test_stack_height_is_independent_after_l2_and_scrollable(self):
        # The real UI starts L1 via a 350ms timer. Disable it for this
        # deterministic GTK layout test: it would clear the test buffer.
        with patch.object(gtk_gui.GLib, "timeout_add", return_value=0):
            win = gtk_gui.InspectorWindow()
        try:
            win.stack.set_transition_type(Gtk.StackTransitionType.NONE)
            self.assertFalse(win.stack.get_vhomogeneous())
            for name in ("overview", "hardware", "health", "workloads",
                         "buyer", "json", "about"):
                scroller = win.stack.get_child_by_name(name)
                self.assertIsInstance(scroller, Gtk.ScrolledWindow)
                self.assertFalse(scroller.get_propagate_natural_height())
            raw = {"schema_version": 1,
                   "purchase_assessment": {"verdict": "do_not_buy"},
                   "health_assessment": {"overall": "critical"}}
            win.report = raw
            win._update_dashboard(gtk_gui.dashboard_model(raw, complete=True))
            win.diagnostics_panel.sessions.append(
                {"level": "L2", "results": {"cpu": {"status": "pass_limited"}}})
            win._on_diagnostic_complete()
            win.hardware_view.get_buffer().set_text("سطر\n" * 800)
            win.hardware_view.queue_resize()
            win.show_all()
            win.resize(950, 650)
            for name in ("health", "hardware", "workloads", "hardware"):
                win.stack.set_visible_child_name(name)
                for _ in range(45):
                    if Gtk.events_pending():
                        Gtk.main_iteration_do(False)
            scroller = win.stack.get_child_by_name("hardware")
            scroller.queue_resize()
            win.hardware_view.queue_resize()
            for _ in range(150):
                if Gtk.events_pending():
                    Gtk.main_iteration_do(False)
            adj = scroller.get_vadjustment()
            self.assertGreater(adj.get_upper(), adj.get_page_size())
            adj.set_value(adj.get_upper() - adj.get_page_size())
            for _ in range(45):
                if Gtk.events_pending():
                    Gtk.main_iteration_do(False)
            self.assertAlmostEqual(adj.get_value(),
                                   adj.get_upper() - adj.get_page_size(),
                                   delta=2.0)
        finally:
            win.destroy()

    def test_color_pixbuf_channels_follow_palette(self):
        from inspector.interactive_gtk_tests import ComponentCheckWindow
        win = ComponentCheckWindow()
        try:
            for idx, rgb in enumerate(((255, 0, 0), (0, 255, 0),
                                       (0, 0, 255), (255, 255, 255),
                                       (0, 0, 0))):
                win._color_index = idx
                win._update_color()
                pixels = win.color_area.get_pixbuf().get_pixels()
                self.assertEqual(tuple(pixels[:3]), rgb)
        finally:
            win.destroy()

    def test_keyboard_reference_only_is_non_destructive(self):
        from inspector.interactive_gtk_tests import ComponentCheckWindow
        win = ComponentCheckWindow()
        try:
            with patch("inspector.interactive_gtk_tests.apply_test_layout") as apply:
                for ident in ("us", "fr", "dz_ar"):
                    win.layout_selector.set_active_id(ident)
                    self.assertEqual(win.layout_selector.get_active_id(), ident)
                apply.assert_not_called()
                self.assertIn("dz(ar)", win.layout_reference.get_text())
        finally:
            win.destroy()

    def test_keyboard_apply_is_opt_in_and_restores_on_close(self):
        from inspector.interactive_gtk_tests import ComponentCheckWindow
        win = ComponentCheckWindow()
        before = {"layout": "us", "model": "pc105"}
        with patch("inspector.interactive_gtk_tests.apply_test_layout",
                   return_value=before) as apply, patch(
                   "inspector.interactive_gtk_tests.restore_x11_layout") as restore:
            win.layout_selector.set_active_id("dz_ar")
            win._apply_layout()
            apply.assert_called_once_with("dz_ar", None)
            win.destroy()
            restore.assert_called_once_with(before)

    def test_interactive_check_window_is_non_destructive_at_start(self):
        from inspector.interactive_gtk_tests import ComponentCheckWindow
        win = ComponentCheckWindow()
        try:
            self.assertEqual(len(win.notebook.get_children()), 5)
            self.assertEqual(win._keys, set())
            self.assertEqual(win._pointer_clicks, 0)
            self.assertIsNone(win._camera)
        finally:
            win.destroy()


if __name__ == "__main__":
    unittest.main()
