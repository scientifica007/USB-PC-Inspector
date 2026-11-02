"""GTK opt-in L2/L3 controls and local HTTPS phone access.

No new tests run at application startup; L1 remains independent and fast.
"""
from __future__ import annotations

import json
import threading

from gi.repository import Gdk, GLib, Gtk, Pango

from .diagnostics import run_level, MANUAL_TESTS
from .phone_bridge import PhoneBridge


def _label(value: str) -> Gtk.Label:
    w = Gtk.Label(label=value)
    w.set_direction(Gtk.TextDirection.RTL)
    w.set_xalign(0)
    w.set_line_wrap(True)
    w.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return w


class DiagnosticsPanel(Gtk.Box):
    def __init__(self, get_report):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_direction(Gtk.TextDirection.RTL)
        self.set_border_width(14)
        self._get_report = get_report
        self.cancel = threading.Event()
        self._working = False
        self.sessions: list[dict] = []

        self.pack_start(_label("الفحص السريع L1 يعمل دائمًا أولًا. اختر مستوى إضافيًا عند الحاجة؛ لن نكتب على القرص الداخلي."), False, False, 0)
        row = Gtk.Box(spacing=8)
        self.l2 = Gtk.Button(label="بدء فحص L2 المتوسط")
        self.l3 = Gtk.Button(label="بدء فحص L3 المعمق")
        self.stop_button = Gtk.Button(label="إلغاء الفحص")
        self.stop_button.set_sensitive(False)
        self.l2.connect("clicked", lambda *_: self.start_level("L2"))
        self.l3.connect("clicked", lambda *_: self.start_level("L3"))
        self.stop_button.connect("clicked", self.stop)
        for button in (self.l2, self.l3, self.stop_button):
            row.pack_start(button, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.status = _label("لا توجد اختبارات إضافية بعد.")
        self.pack_start(self.status, False, False, 0)
        guide = Gtk.Expander(label="اختبارات تفاعلية مطلوبة لبعض القطع (لم تُنفذ)")
        guide.set_direction(Gtk.TextDirection.RTL)
        guide_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for _ident, instruction in MANUAL_TESTS:
            guide_text.pack_start(_label("• " + instruction), False, False, 0)
        guide.add(guide_text)
        self.pack_start(guide, False, False, 0)
        self.result = Gtk.TextView()
        self.result.set_editable(False)
        self.result.set_cursor_visible(False)
        self.result.set_direction(Gtk.TextDirection.RTL)
        self.result.set_justification(Gtk.Justification.LEFT)
        self.result.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(160)
        scroll.add(self.result)
        self.pack_start(scroll, True, True, 0)

    def start_level(self, level: str) -> None:
        if self._working or self._get_report() is None:
            self.status.set_text("أكمل L1 أولًا، ولا تشغل فحصين في وقت واحد.")
            return
        if level == "L3":
            dialog = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.YES_NO,
                text="تأكيد الفحص المعمق L3")
            dialog.format_secondary_text(
                "اختبار CPU محدود الحمل (25 ثانية تقريبًا) و64 MiB RAM؛ "
                "لا اختبار كتابة على القرص. قد ترتفع الحرارة؛ يمكنك الإلغاء.")
            accepted = dialog.run() == Gtk.ResponseType.YES
            dialog.destroy()
            if not accepted:
                return
        self._working = True
        self.cancel = threading.Event()
        self.l2.set_sensitive(False)
        self.l3.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.status.set_text("بدأ " + level + " — تظهر خطوات التنفيذ هنا.")
        threading.Thread(target=self._worker, args=(level, self.cancel),
                         daemon=True).start()

    def _worker(self, level: str, cancel: threading.Event) -> None:
        try:
            session = run_level(
                level,
                progress=lambda item: GLib.idle_add(
                    self.status.set_text, level + ": " + item["step"]
                    + " — " + item["result"].get("status", "?")),
                cancel=cancel)
            GLib.idle_add(self._complete, session, None)
        except Exception as exc:
            GLib.idle_add(self._complete, None, str(exc))

    def _complete(self, session: dict | None, error: str | None) -> bool:
        self._working = False
        self.l2.set_sensitive(True)
        self.l3.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        if error is not None:
            self.status.set_text("فشل تنفيذ الفحص: " + error[:200])
        elif session is not None:
            self.sessions.append(session)
            self.status.set_text("انتهى " + session["level"] + " — " + session["status"])
            self.result.get_buffer().set_text(
                json.dumps(session, ensure_ascii=False, indent=2))
        return False

    def stop(self, *_args) -> None:
        self.cancel.set()
        self.status.set_text("طُلب إلغاء الاختبار، يجري إنهاء المرحلة الحالية.")


class PhonePanel(Gtk.Box):
    def __init__(self, get_report, get_diagnostics):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_direction(Gtk.TextDirection.RTL)
        self.set_border_width(14)
        self._get_report = get_report
        self._get_diagnostics = get_diagnostics
        self.bridge: PhoneBridge | None = None
        self.pack_start(_label(
            "اتصال محلي اختياري دون إنترنت. وصّل الهاتف بنفس شبكة Wi-Fi أو فعّل نقطة الاتصال/USB tethering أولًا."), False, False, 0)
        row = Gtk.Box(spacing=8)
        self.start_button = Gtk.Button(label="فتح خدمة الهاتف")
        self.stop_button = Gtk.Button(label="إغلاق الاتصال")
        self.copy_button = Gtk.Button(label="نسخ رابط الاقتران")
        self.stop_button.set_sensitive(False)
        self.copy_button.set_sensitive(False)
        self.start_button.connect("clicked", self.start)
        self.stop_button.connect("clicked", self.stop)
        self.copy_button.connect("clicked", self.copy_link)
        for b in (self.start_button, self.stop_button, self.copy_button):
            row.pack_start(b, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.state = _label("الخدمة متوقفة؛ لا توجد منافذ شبكة مفتوحة من التطبيق.")
        self.fingerprint = _label("")
        self.pack_start(self.state, False, False, 0)
        self.pack_start(self.fingerprint, False, False, 0)
        self.url = ""

    def start(self, *_args) -> None:
        if self.bridge is not None:
            return
        candidate = PhoneBridge()
        try:
            candidate.set_report(self._get_report())
            candidate.set_diagnostics(self._get_diagnostics())
            details = candidate.start()
        except (OSError, RuntimeError, ValueError) as exc:
            self.state.set_text("لم يبدأ الاتصال: " + str(exc))
            return
        self.bridge = candidate
        self.url = details["url"]
        self.state.set_text("الرابط على الهاتف:\n" + self.url)
        self.fingerprint.set_text(
            "بصمة شهادة TLS (SHA-256): " + details["certificate_sha256"] +
            "\nلا تقبل تحذير الشهادة إلا بعد التأكد من مطابقة البصمة؛ "
            "الشهادة مؤقتة وغير معتمدة من جهة عامة.")
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.copy_button.set_sensitive(True)

    def refresh(self) -> None:
        if self.bridge is not None:
            self.bridge.set_report(self._get_report())
            self.bridge.set_diagnostics(self._get_diagnostics())

    def stop(self, *_args) -> None:
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.url = ""
        self.state.set_text("أُغلقت خدمة الهاتف وأُبطل رمز الاقتران.")
        self.fingerprint.set_text("")
        self.start_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)
        self.copy_button.set_sensitive(False)

    def copy_link(self, *_args) -> None:
        if self.url:
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(self.url, -1)
            clipboard.store()
