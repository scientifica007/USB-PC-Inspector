"""Optional human-assisted component checks; never claim hardware certification.

Screen colours, keyboard input, pointer and speaker/microphone use the running
Live environment. No internal-drive writes, automatic camera capture, or
remote activation. User observations remain explicitly tagged as subjective.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
import shutil
import struct
import subprocess
import threading

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .keyboard_layouts import LAYOUTS, apply_test_layout, restore_x11_layout


PALETTE = (
    ("أحمر", (1.0, 0.0, 0.0)),
    ("أخضر", (0.0, 1.0, 0.0)),
    ("أزرق", (0.0, 0.0, 1.0)),
    ("أبيض", (1.0, 1.0, 1.0)),
    ("أسود", (0.0, 0.0, 0.0)),
)


class ComponentCheckWindow(Gtk.Window):
    def __init__(self, on_result=None):
        super().__init__(title="اختبارات تفاعلية للمكونات — USB PC Inspector")
        self.set_default_size(760, 540)
        self.set_direction(Gtk.TextDirection.RTL)
        self._on_result = on_result
        self._color_index = 0
        self._keys: set[int] = set()
        self._physical_keys: set[int] = set()
        self._keys_by_layout: dict[str, set[int]] = {ident: set() for ident in LAYOUTS}
        self._original_xkb: dict[str, str] | None = None
        self._applied_layout: str | None = None
        self._pointer_moves = 0
        self._pointer_clicks = 0
        self._audio_ok = False
        self._mic_ok = False
        self._camera = None
        self._fullscreen = None
        self._fullscreen_area = None
        self._fullscreen_size = None
        self._reviews = {}
        self._audio_busy = False
        self.connect("destroy", self._clean_up)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(12)
        self.add(root)
        self.notebook = Gtk.Notebook()
        root.pack_start(self.notebook, True, True, 0)

        # Use actual image pixels: Cairo DrawingArea remained gray on HP 630.
        screen = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.color_area = Gtk.Image()
        self.color_area.set_size_request(500, 280)
        self.color_area.set_hexpand(True)
        self.color_area.set_vexpand(True)
        screen.pack_start(self.color_area, True, True, 0)
        self.color_label = Gtk.Label()
        screen.pack_start(self.color_label, False, False, 0)
        next_color = Gtk.Button(label="اللون التالي")
        next_color.connect("clicked", self._next_color)
        screen.pack_start(next_color, False, False, 0)
        fullscreen = Gtk.Button(label="اختبار الألوان بملء الشاشة (Escape للإغلاق)")
        fullscreen.connect("clicked", self._show_fullscreen)
        screen.pack_start(fullscreen, False, False, 0)
        self._add_review(screen, "screen")
        self.notebook.append_page(screen, Gtk.Label(label="الشاشة"))
        self._update_color()

        keys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        choose = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        choose.pack_start(Gtk.Label(label="تخطيط لوحة المفاتيح:"), False, False, 0)
        self.layout_selector = Gtk.ComboBoxText()
        for ident, spec in LAYOUTS.items():
            self.layout_selector.append(ident, spec[0])
        self.layout_selector.set_active_id("us")
        self.layout_selector.connect("changed", self._layout_changed)
        choose.pack_start(self.layout_selector, True, True, 0)
        keys.pack_start(choose, False, False, 0)
        self.layout_reference = Gtk.Label()
        self.layout_reference.set_line_wrap(True)
        self.layout_reference.set_justify(Gtk.Justification.CENTER)
        keys.pack_start(self.layout_reference, False, False, 0)
        apply_layout = Gtk.Button(label="تطبيق التخطيط المختار مؤقتًا على جلسة Live")
        apply_layout.connect("clicked", self._apply_layout)
        keys.pack_start(apply_layout, False, False, 0)
        self.layout_status = Gtk.Label(
            label="الاختيار للعرض فقط؛ لا يتغير تخطيط الكتابة إلا بالضغط على تطبيق.")
        self.layout_status.set_line_wrap(True)
        keys.pack_start(self.layout_status, False, False, 0)
        self._layout_changed()
        self.key_label = Gtk.Label(label="اضغط مفاتيح مختلفة داخل هذه النافذة ثم قيّمها بنفسك.")
        keys.pack_start(self.key_label, False, False, 0)
        keys.set_can_focus(True)
        self.keys_area = keys
        keys.connect("key-press-event", self._keypress)
        self.connect("key-press-event", self._keypress)
        activate_keys = Gtk.Button(label="تفعيل التقاط المفاتيح")
        activate_keys.connect("clicked", lambda *_: keys.grab_focus())
        keys.pack_start(activate_keys, False, False, 0)
        self._add_review(keys, "keyboard")
        self.notebook.append_page(keys, Gtk.Label(label="لوحة المفاتيح"))
        self.notebook.connect("switch-page", self._on_switch_page)

        pointer = Gtk.EventBox()
        pointer.set_visible_window(True)
        pointer.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.pointer_label = Gtk.Label(label="حرّك المؤشر هنا وانقر؛ جرب لوحة اللمس نفسها لا فأرة خارجية.")
        pointer.add(self.pointer_label)
        pointer.connect("motion-notify-event", self._motion)
        pointer.connect("button-press-event", self._click)
        pointer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        pointer_box.pack_start(pointer, True, True, 0)
        self._add_review(pointer_box, "pointer")
        self.notebook.append_page(pointer_box, Gtk.Label(label="لوحة اللمس"))

        audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.audio_label = Gtk.Label(label="الصوت يحتاج تأكيدك السمعي؛ التسجيل يبقى في RAM ولا يُحفَظ.")
        audio.pack_start(self.audio_label, False, False, 0)
        play = Gtk.Button(label="تشغيل نغمة السماعة")
        record = Gtk.Button(label="تسجيل 3 ثوانٍ ثم سماع الميكروفون")
        play.connect("clicked", lambda *_: self._audio_job("play"))
        record.connect("clicked", lambda *_: self._audio_job("record"))
        audio.pack_start(play, False, False, 0)
        audio.pack_start(record, False, False, 0)
        audio.pack_start(Gtk.Label(label="سعة نغمة السماعات داخل التطبيق (لا تغيّر إعدادات الجهاز)"), False, False, 0)
        self.playback_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.1, 0.9, 0.05)
        self.playback_scale.set_value(0.4)
        audio.pack_start(self.playback_scale, False, False, 0)
        audio.pack_start(Gtk.Label(label="تضخيم إعادة سماع التسجيل رقميًا (ليس حساسية ميكروفون العتاد)"), False, False, 0)
        self.mic_replay_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 6, 0.5)
        self.mic_replay_scale.set_value(2)
        audio.pack_start(self.mic_replay_scale, False, False, 0)
        self._add_review(audio, "speaker")
        self._add_review(audio, "microphone")
        self.notebook.append_page(audio, Gtk.Label(label="الصوت والميكروفون"))

        camera = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.camera_label = Gtk.Label(label="اختبار كاميرا اختياري؛ لا يحتفظ بصور أو فيديو.")
        open_cam = Gtk.Button(label="عرض الكاميرا محليًا")
        open_cam.connect("clicked", self._open_camera)
        camera.pack_start(self.camera_label, False, False, 0)
        camera.pack_start(open_cam, False, False, 0)
        self._add_review(camera, "camera")
        self.notebook.append_page(camera, Gtk.Label(label="الكاميرا"))

        root.pack_start(Gtk.Label(label="هذه اختبارات تفاعلية محدودة؛ نجاحها لا يثبت خلو القطع من العيوب الكامنة."), False, False, 0)
        done = Gtk.Button(label="تسجيل ملاحظات الاختبار وإغلاق")
        done.connect("clicked", self._finish)
        root.pack_start(done, False, False, 0)

    def _add_review(self, parent, key):
        """Explicit subjective result; execution of a probe is not a pass."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.pack_start(Gtk.Label(label="حكمك على الاختبار:"), False, False, 0)
        choice = Gtk.ComboBoxText()
        for ident, title in (("not_tested", "لم أقيّم"),
                             ("pass", "نجح"),
                             ("fail", "فشل / مشكلة"),
                             ("inconclusive", "غير حاسم")):
            choice.append(ident, title)
        choice.set_active_id("not_tested")
        row.pack_start(choice, False, False, 0)
        note = Gtk.Entry()
        note.set_placeholder_text("ملاحظة اختيارية — ما الذي شاهدته أو سمعته؟")
        note.set_max_length(300)
        row.pack_start(note, True, True, 0)
        parent.pack_start(row, False, False, 0)
        self._reviews[key] = (choice, note)

    def _on_switch_page(self, _notebook, _page, index):
        if index == 1:
            GLib.idle_add(self.keys_area.grab_focus)

    def _show_fullscreen(self, *_args):
        if self._fullscreen is not None:
            self._fullscreen.present()
            return
        win = Gtk.Window(title="فحص ألوان الشاشة — Escape للإغلاق")
        win.set_transient_for(self)
        win.set_direction(Gtk.TextDirection.RTL)
        area = Gtk.Image()
        area.set_hexpand(True)
        area.set_vexpand(True)
        win.add(area)
        win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        win.connect("button-press-event", self._fullscreen_click)
        win.connect("key-press-event", self._fullscreen_key)
        win.connect("size-allocate", self._fullscreen_allocated)
        win.connect("destroy", self._fullscreen_closed)
        self._fullscreen, self._fullscreen_area = win, area
        self._fullscreen_size = None
        win.show_all()
        win.fullscreen()
        self._update_color()

    def _fullscreen_click(self, *_args):
        self._next_color()
        return True

    def _fullscreen_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self._fullscreen.destroy()
            return True
        if event.keyval in (Gdk.KEY_space, Gdk.KEY_Return):
            self._next_color()
            return True
        return False

    def _fullscreen_closed(self, *_args):
        self._fullscreen = None
        self._fullscreen_area = None
        self._fullscreen_size = None

    @staticmethod
    def _solid_pixbuf(rgb: tuple[float, float, float],
                      width: int, height: int) -> GdkPixbuf.Pixbuf:
        width = max(1, min(int(width), 4096))
        height = max(1, min(int(height), 2160))
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8,
                                      width, height)
        channels = [round(max(0, min(1, x)) * 255) for x in rgb]
        pixbuf.fill((channels[0] << 24) | (channels[1] << 16)
                    | (channels[2] << 8) | 0xFF)
        return pixbuf

    def _fullscreen_allocated(self, _widget, allocation) -> None:
        current = (allocation.width, allocation.height)
        if current != self._fullscreen_size and self._fullscreen_area is not None:
            self._fullscreen_size = current
            self._render_fullscreen_color()

    def _render_fullscreen_color(self) -> None:
        if self._fullscreen_area is None:
            return
        width, height = self._fullscreen_size or (800, 500)
        self._fullscreen_area.set_from_pixbuf(
            self._solid_pixbuf(PALETTE[self._color_index][1], width, height))

    def _update_color(self) -> None:
        self.color_label.set_text(
            PALETTE[self._color_index][0] + " — تحقق بصريًا من عدم وجود بقع أو خطوط أو بكسلات عالقة.")
        self.color_area.set_from_pixbuf(
            self._solid_pixbuf(PALETTE[self._color_index][1], 500, 280))
        self._render_fullscreen_color()

    def _layout_changed(self, *_args) -> None:
        ident = self.layout_selector.get_active_id() or "us"
        self.layout_reference.set_text(
            "مرجع الصفوف (مواضع المفاتيح):\n" + LAYOUTS[ident][3]
            + "\nلا يمثّل المرجع اختبارًا آليًا لسلامة كل مفتاح.")

    def _apply_layout(self, *_args) -> None:
        ident = self.layout_selector.get_active_id() or "us"
        try:
            self._original_xkb = apply_test_layout(ident, self._original_xkb)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.layout_status.set_text("تعذر تغيير تخطيط جلسة X11: " + str(exc)[:190])
            return
        self._applied_layout = ident
        self.layout_status.set_text(
            "تم تطبيق " + LAYOUTS[ident][0] +
            " مؤقتًا. سيُسترجع تخطيط X11 الأصلي عند إغلاق نافذة الاختبار.")
        self.keys_area.grab_focus()

    def _next_color(self, *_args) -> None:
        self._color_index = (self._color_index + 1) % len(PALETTE)
        self._update_color()

    def _keypress(self, _widget, event) -> bool:
        # Events on other pages (e.g. typing notes) are not keyboard tests.
        if self.notebook.get_current_page() != 1:
            return False
        value = int(event.keyval)
        self._keys.add(value)
        physical = getattr(event, "hardware_keycode", None)
        if physical is not None:
            self._physical_keys.add(int(physical))
        ident = self.layout_selector.get_active_id() or "us"
        self._keys_by_layout[ident].add(int(physical) if physical is not None else value)
        name = Gdk.keyval_name(value) or str(value)
        name = {"Return": "Enter / Return", "Print": "Impr écran / Print Screen",
                "Escape": "Échap / Escape"}.get(name, name)
        self.key_label.set_text(
            "مفاتيح فيزيائية/رموز مختلفة: " + str(len(self._keys_by_layout[ident]))
            + " — الأخير: " + name
            + (" (رمز فيزيائي: " + str(physical) + ")" if physical is not None else "")
            + "\nبعض مفاتيح F قد يعترضها مدير النوافذ؛ لا تعتبرها معطلة تلقائيًا.")
        return False

    def _motion(self, *_args) -> bool:
        self._pointer_moves += 1
        self._pointer_status()
        return False

    def _click(self, *_args) -> bool:
        self._pointer_clicks += 1
        self._pointer_status()
        return False

    def _pointer_status(self):
        if self._pointer_moves % 12 == 0 or self._pointer_clicks:
            self.pointer_label.set_text(
                "حركة مؤشر: " + str(self._pointer_moves)
                + " | نقرات: " + str(self._pointer_clicks)
                + "\nهذه أحداث المؤشر، ولا تثبت مصدرها (Touchpad أو Mouse).")

    @staticmethod
    def _tone(amplitude: float = 0.4) -> bytes:
        amplitude = max(0.1, min(0.9, float(amplitude)))
        return b"".join(
            struct.pack("<h", int(amplitude * 32767 * math.sin(2*math.pi*440*i/16000)))
            for i in range(16000))

    @staticmethod
    def _amplify_pcm(sound: bytes, gain: float) -> bytes:
        gain = max(1.0, min(float(gain), 6.0))
        return b"".join(struct.pack("<h", max(-32768, min(32767, int(sample * gain))))
                        for (sample,) in struct.iter_unpack("<h", sound[:len(sound) & ~1]))

    def _audio_job(self, mode):
        if self._audio_busy:
            self.audio_label.set_text("اختبار الصوت السابق جارٍ؛ لا تبدأ عملية متزامنة.")
            return
        self._audio_busy = True
        volume = self.playback_scale.get_value()
        replay_gain = self.mic_replay_scale.get_value()
        def work():
            try:
                if not shutil.which("aplay"):
                    raise RuntimeError("aplay غير متوفر")
                if mode == "play":
                    sound = self._tone(volume)
                else:
                    if not shutil.which("arecord"):
                        raise RuntimeError("arecord غير متوفر")
                    r = subprocess.run(["arecord", "-q", "-d", "3", "-t", "raw",
                                        "-f", "S16_LE", "-r", "16000", "-c", "1"],
                                       capture_output=True, timeout=8, check=False)
                    if r.returncode:
                        raise RuntimeError("تعذر تسجيل الصوت: " + r.stderr.decode(errors="replace")[-120:])
                    sound = self._amplify_pcm(r.stdout, replay_gain)
                p = subprocess.run(["aplay", "-q", "-t", "raw", "-f", "S16_LE",
                                    "-r", "16000", "-c", "1"], input=sound,
                                   capture_output=True, timeout=9, check=False)
                if p.returncode:
                    raise RuntimeError("تعذر إخراج الصوت")
                GLib.idle_add(self.audio_label.set_text,
                              "نفذ الاختبار " + mode + "؛ استمع وقيّم الجودة بنفسك.")
                if mode == "play":
                    self._audio_ok = True
                else:
                    self._mic_ok = True
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                GLib.idle_add(self.audio_label.set_text, "تعذّر الاختبار: " + str(exc)[:200])
            finally:
                GLib.idle_add(self._audio_job_complete)
        threading.Thread(target=work, daemon=True).start()

    def _audio_job_complete(self):
        self._audio_busy = False
        return False

    def _open_camera(self, *_args):
        if self._camera is not None and self._camera.poll() is None:
            self.camera_label.set_text("الكاميرا تعمل في نافذة أخرى.")
            return
        if not shutil.which("gst-launch-1.0"):
            self.camera_label.set_text("خدمة GStreamer غير موجودة في هذا النظام.")
            return
        if not __import__("glob").glob("/dev/video[0-9]*"):
            self.camera_label.set_text("لم تظهر كاميرا متوافقة في /dev/video*.")
            return
        try:
            self._camera = subprocess.Popen(
                ["gst-launch-1.0", "-m", "v4l2src", "device=/dev/video0",
                 "!", "videoconvert", "!", "autovideosink"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except OSError as exc:
            self.camera_label.set_text("تعذر تشغيل معاينة الكاميرا: " + str(exc)[:160])
            return
        self.camera_label.set_text(
            "طُلب تشغيل المعاينة؛ لا يُعد الضوء وحده إثباتًا للصورة. تحقق بصريًا.")
        proc = self._camera
        def watch():
            try:
                _out, err = proc.communicate()
                detail = err.decode(errors="replace")[-300:].strip()
                GLib.idle_add(self._camera_ended, proc, detail)
            except OSError:
                pass
        threading.Thread(target=watch, daemon=True).start()

    def _camera_ended(self, proc, detail):
        if self._camera is proc and self.get_visible():
            self.camera_label.set_text(
                "انتهت المعاينة؛ " + (detail or "لم يقدم المحرك تأكيدًا على وصول الصورة."))
        return False

    def _finish(self, *_args):
        if self._audio_busy:
            self.audio_label.set_text("انتظر اكتمال التسجيل أو التشغيل قبل إغلاق النتائج.")
            return
        verdicts = {
            key: {"status": choice.get_active_id() or "not_tested",
                  "note": note.get_text().strip()}
            for key, (choice, note) in self._reviews.items()
        }
        if self._on_result is not None:
            self._on_result({
                "level": "interactive",
                "status": "user_assisted_partial",
                "completed_utc": datetime.now(timezone.utc).isoformat(),
                "user_verdicts": verdicts,
                "results": {
                    "screen": {"status": "user_review_required",
                               "colours_available": [name for name, _ in PALETTE]},
                    "keyboard": {"status": "events_observed" if self._keys else "not_tested",
                                 "distinct_key_codes": len(self._keys),
                                 "distinct_physical_key_codes": len(self._physical_keys),
                                 "reference_layout": self.layout_selector.get_active_id(),
                                 "applied_xkb_layout": self._applied_layout,
                                 "physical_codes_by_layout": {
                                     key: sorted(values)[:128]
                                     for key, values in self._keys_by_layout.items()}},
                    "pointer": {"status": "events_observed" if self._pointer_moves or self._pointer_clicks else "not_tested",
                                "moves": self._pointer_moves, "clicks": self._pointer_clicks},
                    "speaker": {"status": "output_attempted" if self._audio_ok else "not_tested"},
                    "microphone": {"status": "record_and_play_attempted" if self._mic_ok else "not_tested"},
                    "camera": {"status": "preview_requested" if self._camera else "not_tested"},
                },
                "limitations": "النتائج الذاتية موسومة بتقييم المستخدم؛ مجرد تشغيل اختبار لا يعني نجاحه.",
            })
        self.destroy()

    def _clean_up(self, *_args):
        if self._fullscreen is not None:
            self._fullscreen.destroy()
        if self._original_xkb is not None:
            try:
                restore_x11_layout(self._original_xkb)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                # Best effort if the X server has gone away; no system files.
                pass
            self._original_xkb = None
        if self._camera is not None and self._camera.poll() is None:
            self._camera.terminate()
            try:
                self._camera.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._camera.kill()
