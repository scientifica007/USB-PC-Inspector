"""GTK 3 Arabic-first, right-to-left hardware dashboard.

GTK/Pango provides native Arabic glyph shaping and bidirectional layout.
Scanning and verified USB persistence are delegated to the existing backend;
the report schema, collector, SMART evidence and save protocol are unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from . import __version__
from .desktop_backend import collect_l1, save_to_usb
from .ui_model import dashboard_model

STYLESHEET = """
window { background: #f4f6fa; color: #1d2939; font-family: "Noto Sans Arabic", "Noto Naskh Arabic", sans-serif; }
.app-header { padding: 10px 4px 6px; }
.app-title { font-size: 24px; font-weight: bold; color: #14263c; }
.secondary { color: #51647a; font-size: 12px; }
.status { color: #405a78; font-size: 12px; }
.decision { border-radius: 12px; border: 1px solid #dae1e8; background: #f1f5f9; padding: 18px; }
.decision.danger { background: #fff0ee; border-color: #e3b5b0; }
.decision.warning { background: #fff7e8; border-color: #e7d2a3; }
.decision.candidate { background: #edf6f2; border-color: #c0dfd2; }
.decision-title { font-size: 21px; font-weight: bold; color: #1c3550; }
.decision.danger .decision-title { color: #973632; }
.decision.warning .decision-title { color: #825a1c; }
.decision.candidate .decision-title { color: #245c4a; }
.decision-reason { font-size: 13px; color: #38485c; }
.section-title { font-weight: bold; color: #20344b; font-size: 14px; }
.fact { background: #ffffff; border-radius: 10px; border: 1px solid #e0e5eb; padding: 12px; }
.fact-label { color: #586a7d; font-size: 11px; }
.fact-value { color: #1c2d42; font-weight: bold; font-size: 14px; }
.note { padding: 7px 10px; border-radius: 5px; background: #fffaf1; color: #394c61; font-size: 12px; }
.toolbar button { padding: 8px 14px; border-radius: 7px; }
.primary-action { background: #234c7c; color: white; font-weight: bold; border-color: #234c7c; }
.primary-action:disabled { background: #dde4ed; color: #6c7f92; border-color: #dde4ed; }
stack, scrolledwindow { background: transparent; }
.about { padding: 18px; }
"""


def label(text: str, style: str | None = None, *, wrap: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text)
    widget.set_xalign(1.0)
    widget.set_yalign(0.5)
    widget.set_selectable(False)
    widget.set_hexpand(True)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class InspectorWindow(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="USB PC Inspector — فحص الحواسيب")
        self.set_default_size(1040, 680)
        self.set_size_request(760, 550)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_direction(Gtk.TextDirection.RTL)
        self.connect("destroy", Gtk.main_quit)
        self.report: dict | None = None
        self.scanning = False
        self.saving = False

        self._install_style()
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main.set_border_width(16)
        self.add(main)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        header.get_style_context().add_class("app-header")
        header.pack_start(label("USB PC Inspector", "app-title"), False, False, 0)
        header.pack_start(
            label("فحص سريع وآمن قبل الشراء — دون تعديل الأقراص الداخلية", "secondary"),
            False, False, 0,
        )
        main.pack_start(header, False, False, 0)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toolbar.get_style_context().add_class("toolbar")
        self.scan_button = Gtk.Button(label="إعادة الفحص")
        self.scan_button.connect("clicked", self.scan)
        self.save_button = Gtk.Button(label="حفظ التقرير على USB")
        self.save_button.get_style_context().add_class("primary-action")
        self.save_button.set_sensitive(False)
        self.save_button.connect("clicked", self.save)
        self.copy_button = Gtk.Button(label="نسخ JSON")
        self.copy_button.set_sensitive(False)
        self.copy_button.connect("clicked", self.copy_json)
        toolbar.pack_start(self.scan_button, False, False, 0)
        toolbar.pack_start(self.save_button, False, False, 0)
        toolbar.pack_start(self.copy_button, False, False, 0)
        main.pack_start(toolbar, False, False, 0)

        self.status = label("سيبدأ فحص الجهاز تلقائيًا...", "status", wrap=True)
        main.pack_start(self.status, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self.stack)
        main.pack_start(switcher, False, False, 0)
        main.pack_start(self.stack, True, True, 0)

        self._build_overview()
        self._build_json_tab()
        self._build_about_tab()
        self._update_dashboard(dashboard_model({}))
        GLib.timeout_add(350, self.scan)

    @staticmethod
    def _install_style() -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(STYLESHEET.encode("utf-8"))
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build_overview(self) -> None:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        outer.set_border_width(6)
        scroller.add(outer)

        decision = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.decision = decision
        decision.get_style_context().add_class("decision")
        self.decision_title = label("", "decision-title", wrap=True)
        self.decision_reason = label("", "decision-reason", wrap=True)
        decision.pack_start(self.decision_title, False, False, 0)
        decision.pack_start(self.decision_reason, False, False, 0)
        outer.pack_start(decision, False, False, 0)

        outer.pack_start(label("المواصفات المكتشفة", "section-title"), False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12)
        grid.set_column_homogeneous(True)
        self.fact_labels: list[Gtk.Label] = []
        self.fact_titles: list[Gtk.Label] = []
        titles = ("الجهاز", "المعالج", "الذاكرة المركبة / التي يراها النظام",
                  "التخزين الداخلي", "SMART", "البطارية")
        for index, title in enumerate(titles):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.get_style_context().add_class("fact")
            title_label = label(title, "fact-label", wrap=True)
            card.pack_start(title_label, False, False, 0)
            self.fact_titles.append(title_label)
            value_label = label("قيد الفحص", "fact-value", wrap=True)
            value_label.set_valign(Gtk.Align.START)
            card.pack_start(value_label, True, True, 0)
            self.fact_labels.append(value_label)
            grid.attach(card, index % 2, index // 2, 1, 1)
        outer.pack_start(grid, False, False, 0)

        outer.pack_start(label("الأدلة والتحذيرات", "section-title"), False, False, 0)
        self.notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.pack_start(self.notes_box, False, False, 0)

        self.timing_label = label("", "secondary")
        outer.pack_start(self.timing_label, False, False, 0)
        self.scope_label = label(
            "تقييم L1 أولي؛ لا يثبت سلامة الجهاز أو السعر أو الضمان.",
            "secondary", wrap=True,
        )
        outer.pack_start(self.scope_label, False, False, 0)
        self.stack.add_titled(scroller, "overview", "النتيجة السريعة")

    def _build_json_tab(self) -> None:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.NONE)
        view.set_direction(Gtk.TextDirection.LTR)
        view.set_left_margin(16)
        view.set_right_margin(16)
        view.set_top_margin(12)
        view.set_bottom_margin(12)
        self.json_view = view
        scroller.add(view)
        self.stack.add_titled(scroller, "json", "البيانات الفنية JSON")

    def _build_about_tab(self) -> None:
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.get_style_context().add_class("about")
        about_lines = (
            f"USB PC Inspector — الإصدار {__version__}",
            "هذه أداة فحص أولي تعتمد قراءة بيانات الأجهزة دون تعديل القرص الداخلي.",
            "يبدأ الفحص تلقائيًا. النتائج المرحلية للتعريف فقط؛ ولا يظهر قرار الشراء إلا بعد اكتمال الجرد.",
            "يُحفظ التقرير الدائم بصيغتي JSON وHTML مع ملف complete.json للتحقق من SHA-256، على قسم USB خارجي قابل للكتابة موسوم PCINSPDATA أو Ventoy.",
            "إذا فشل الحفظ يبقى التقرير في ذاكرة التطبيق طوال الجلسة ويمكن إعادة محاولة الحفظ دون إعادة الفحص.",
            "لا يشمل هذا المستوى اختبار إجهاد أو اختبار RAM كاملًا أو فحص الشاشة والمنافذ، ولا يقيّم السعر أو الضمان.",
            "للعرض العربي استخدمت واجهة GTK 3 مع تشكيل الحروف واتجاه RTL؛ صفحة JSON الفنية باتجاه LTR.",
        )
        for item in about_lines:
            box.pack_start(label(item, "secondary", wrap=True), False, False, 0)
        scroller.add(box)
        self.stack.add_titled(scroller, "about", "حول الفحص")

    def _update_dashboard(self, model: dict) -> None:
        style = self.decision.get_style_context()
        for tone in ("danger", "warning", "candidate", "neutral", "pending"):
            style.remove_class(tone)
        style.add_class(model["tone"])
        self.decision_title.set_text(model["label"])
        self.decision_reason.set_text(model["reason"])
        self.status.set_text(model["state"])
        for title_widget, widget, (key, value) in zip(
                self.fact_titles, self.fact_labels, model["facts"]):
            title_widget.set_text(key)
            widget.set_text(value)
        for child in self.notes_box.get_children():
            self.notes_box.remove(child)
        notes = model["notes"] if model["complete"] else [
            "التحذيرات والقرار النهائي لا يظهران حتى اكتمال الفحص."
        ]
        if not notes:
            notes = ["لا توجد تحذيرات مدرجة، لكن الفحص الأولي ليس شهادة سلامة."]
        for note in notes:
            row = label("• " + note, "note", wrap=True)
            self.notes_box.pack_start(row, False, False, 0)
        self.notes_box.show_all()
        self.timing_label.set_text("زمن الفحص: " + model["timing"])
        self.scope_label.set_text(model["scope"])

    def _emit(self, kind: str, payload: object) -> None:
        GLib.idle_add(self._receive, kind, payload)

    def scan(self, *_args) -> bool:
        if self.scanning or self.saving:
            return False
        self.scanning = True
        self.report = None
        self.scan_button.set_sensitive(False)
        self.save_button.set_sensitive(False)
        self.copy_button.set_sensitive(False)
        self.json_view.get_buffer().set_text("")
        self.stack.set_visible_child_name("overview")
        self._update_dashboard(dashboard_model({}))
        self.status.set_text("يجري الفحص — تظهر المكونات تباعًا...")
        threading.Thread(target=self._scan_worker, daemon=True).start()
        return False

    def _scan_worker(self) -> None:
        try:
            collect_l1(self._emit)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            self._emit("scan_error", str(exc))

    def _receive(self, kind: str, payload: object) -> bool:
        if kind == "progress":
            event = payload if isinstance(payload, dict) else {}
            snapshot = event.get("snapshot") or {}
            self._update_dashboard(dashboard_model(
                snapshot, stage=event.get("stage"),
                elapsed=event.get("elapsed_seconds")
            ))
        elif kind == "reset":
            self._update_dashboard(dashboard_model({}))
            self.status.set_text("فشل جمع بعض البيانات بالصلاحيات الموسعة؛ تجري محاولة محدودة.")
        elif kind == "complete":
            report, reduced = payload
            self.report = report
            self.scanning = False
            self.scan_button.set_sensitive(True)
            self.save_button.set_sensitive(True)
            self.copy_button.set_sensitive(True)
            self._update_dashboard(dashboard_model(report, complete=True, reduced=reduced))
            self.json_view.get_buffer().set_text(json.dumps(
                report, ensure_ascii=False, indent=2
            ))
        elif kind == "saved":
            self.saving = False
            self.scan_button.set_sensitive(True)
            self.save_button.set_sensitive(True)
            self.status.set_text("حُفظ التقرير على USB مع التحقق من سلامة الملفات.")
            folder = Path(str(payload.get("json") or "")).parent
            self._dialog(
                "تم حفظ التقرير",
                "حُفظ ملفا JSON وHTML وملف التحقق complete.json.\n"
                f"المجلد: {folder}\n"
                "التحقق النهائي بعد إخراج USB وإعادة فتح الملفات.",
                Gtk.MessageType.INFO,
            )
        elif kind == "save_error":
            self.saving = False
            self.scan_button.set_sensitive(True)
            self.save_button.set_sensitive(self.report is not None)
            self.status.set_text("لم يُحفظ التقرير — ما زالت البيانات في الذاكرة.")
            self._dialog(
                "تعذّر الحفظ على USB",
                str(payload) + "\nيمكن إعادة محاولة الحفظ دون إعادة الفحص.",
                Gtk.MessageType.WARNING,
            )
        elif kind == "scan_error":
            self.scanning = False
            self.scan_button.set_sensitive(True)
            self.status.set_text("تعذر إكمال الفحص. لم يصدر قرار شراء.")
            self._dialog("خطأ أثناء الفحص", str(payload), Gtk.MessageType.WARNING)
        return False

    def _dialog(self, title: str, details: str, kind: Gtk.MessageType) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=Gtk.DialogFlags.MODAL,
            message_type=kind, buttons=Gtk.ButtonsType.OK, text=title
        )
        dialog.format_secondary_text(details)
        dialog.set_direction(Gtk.TextDirection.RTL)
        dialog.run()
        dialog.destroy()

    def save(self, *_args) -> None:
        if self.report is None or self.scanning or self.saving:
            return
        report = self.report
        self.saving = True
        self.save_button.set_sensitive(False)
        self.scan_button.set_sensitive(False)
        self.status.set_text("يجري حفظ التقرير والتحقق من الملفات على USB...")
        threading.Thread(target=self._save_worker, args=(report,), daemon=True).start()

    def _save_worker(self, report: dict) -> None:
        try:
            receipt = save_to_usb(report)
            self._emit("saved", receipt)
        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
            self._emit("save_error", str(exc))

    def copy_json(self, *_args) -> None:
        if self.report is None:
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(json.dumps(self.report, ensure_ascii=False, indent=2), -1)
        clipboard.store()
        self.status.set_text("نُسخ JSON إلى الحافظة؛ لم يُحفظ ملف دائم بهذه العملية.")


def main() -> None:
    Gtk.Widget.set_default_direction(Gtk.TextDirection.RTL)
    window = InspectorWindow()
    window.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
