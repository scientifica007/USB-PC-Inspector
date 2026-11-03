"""GTK opt-in L2/L3 controls and local HTTPS phone access.

No new tests run at application startup; L1 remains independent and fast.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

from .diagnostics import run_level, MANUAL_TESTS
from .phone_bridge import PhoneBridge
from .interactive_gtk_tests import ComponentCheckWindow


def _label(value: str) -> Gtk.Label:
    w = Gtk.Label(label=value)
    w.set_direction(Gtk.TextDirection.RTL)
    w.set_xalign(0)
    w.set_line_wrap(True)
    w.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return w


class DiagnosticsPanel(Gtk.Box):
    def __init__(self, get_report, on_complete=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_direction(Gtk.TextDirection.RTL)
        self.set_border_width(14)
        self._get_report = get_report
        self._on_complete = on_complete
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
        self.interactive_button = Gtk.Button(label="اختبار القطع تفاعليًا")
        self.interactive_button.connect("clicked", self.open_interactive)
        for button in (self.l2, self.l3, self.stop_button, self.interactive_button):
            row.pack_start(button, False, False, 0)
        self.pack_start(row, False, False, 0)
        duration_row = Gtk.Box(spacing=8)
        duration_row.pack_start(_label("مدة اختبار CPU في L3 (بالدقائق):"), False, False, 0)
        self.deep_minutes = Gtk.SpinButton.new_with_range(1, 30, 1)
        self.deep_minutes.set_value(15)
        duration_row.pack_start(self.deep_minutes, False, False, 0)
        self.pack_start(duration_row, False, False, 0)
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
                "اختبار CPU لمدة " + str(int(self.deep_minutes.get_value()))
                + " دقيقة و64 MiB RAM؛ لا اختبار كتابة على القرص. "
                "قد ترتفع الحرارة؛ يمكنك الإلغاء.")
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
        seconds = float(self.deep_minutes.get_value()) * 60 if level == "L3" else 1.0
        threading.Thread(target=self._worker, args=(level, self.cancel, seconds),
                         daemon=True).start()

    def _worker(self, level: str, cancel: threading.Event, seconds: float) -> None:
        try:
            session = run_level(
                level,
                progress=lambda item: GLib.idle_add(
                    self.status.set_text, level + ": " + item["step"]
                    + " — " + str(item["result"].get("status",
                                        item["result"].get("elapsed_seconds", "?")))),
                cancel=cancel, cpu_seconds=seconds)
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
            if self._on_complete is not None:
                self._on_complete()
            self.status.set_text("انتهى " + session["level"] + " — " + session["status"])
            self.result.get_buffer().set_text(
                json.dumps(session, ensure_ascii=False, indent=2))
        return False

    def stop(self, *_args) -> None:
        self.cancel.set()
        self.status.set_text("طُلب إلغاء الاختبار، يجري إنهاء المرحلة الحالية.")

    def open_interactive(self, *_args) -> None:
        window = ComponentCheckWindow(self._interactive_result)
        window.set_transient_for(self.get_toplevel())
        window.show_all()

    def _interactive_result(self, session: dict) -> None:
        self.sessions.append(session)
        self.status.set_text("حُفظت نتائج اختبار المكونات التفاعلي المحدود في الجلسة.")
        self.result.get_buffer().set_text(json.dumps(session, ensure_ascii=False, indent=2))
        if self._on_complete is not None:
            self._on_complete()


class PhonePanel(Gtk.Box):
    def __init__(self, get_report, get_diagnostics):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_direction(Gtk.TextDirection.RTL)
        self.set_border_width(14)
        self._get_report = get_report
        self._get_diagnostics = get_diagnostics
        self.bridge: PhoneBridge | None = None
        self._starting = False
        self._start_serial = 0
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
        self.qr_image = Gtk.Image()
        self.pack_start(self.qr_image, False, False, 0)
        self.pack_start(self.fingerprint, False, False, 0)
        self.url = ""

    def start(self, *_args) -> None:
        if self.bridge is not None or self._starting:
            return
        self._starting = True
        self._start_serial += 1
        serial = self._start_serial
        candidate = PhoneBridge()
        candidate.set_report(self._get_report())
        candidate.set_diagnostics(self._get_diagnostics())
        self.start_button.set_sensitive(False)
        self.state.set_text("جارٍ اكتشاف عنوان الشبكة وتهيئة USB tethering عند الحاجة…")
        # DHCP and local certificate generation must not freeze the GTK event loop.
        def work():
            try:
                details = candidate.start()
            except (OSError, RuntimeError, ValueError) as exc:
                GLib.idle_add(self._start_failed, serial, str(exc))
                return
            GLib.idle_add(self._start_ready, serial, candidate, details)
        threading.Thread(target=work, daemon=True).start()

    def _start_failed(self, serial: int, reason: str) -> bool:
        if serial != self._start_serial:
            return False
        self._starting = False
        self.start_button.set_sensitive(True)
        self.state.set_text("لم يبدأ الاتصال: " + reason[:500])
        return False

    def _start_ready(self, serial: int, candidate: PhoneBridge, details: dict) -> bool:
        if serial != self._start_serial:
            candidate.stop()
            return False
        self._starting = False
        self.bridge = candidate
        self.url = details["url"]
        self.state.set_text("الرابط على الهاتف:\n" + self.url)
        if shutil.which("qrencode"):
            try:
                rendered = subprocess.run(
                    ["qrencode", "-t", "PNG", "-o", "-", "-s", "4", self.url],
                    capture_output=True, check=False, timeout=5)
                if rendered.returncode == 0:
                    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                    loader.write(rendered.stdout)
                    loader.close()
                    self.qr_image.set_from_pixbuf(loader.get_pixbuf())
            except (OSError, ValueError, GLib.Error, subprocess.TimeoutExpired):
                pass
        self.fingerprint.set_text(
            "بصمة شهادة TLS (SHA-256): " + details["certificate_sha256"] +
            "\nتأكد من مطابقة بصمة الشهادة قبل قبول الاتصال.")
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)
        self.copy_button.set_sensitive(True)
        return False

    def refresh(self) -> None:
        if self.bridge is not None:
            self.bridge.set_report(self._get_report())
            self.bridge.set_diagnostics(self._get_diagnostics())

    def stop(self, *_args) -> None:
        self._start_serial += 1
        self._starting = False
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.url = ""
        self.qr_image.clear()
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
