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

from gi.repository import Gdk, GLib, Gtk


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
        self._pointer_moves = 0
        self._pointer_clicks = 0
        self._audio_ok = False
        self._mic_ok = False
        self._camera = None
        self._fullscreen = None
        self._fullscreen_area = None
        self._reviews = {}
        self._audio_busy = False
        self.connect("destroy", self._clean_up)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_border_width(12)
        self.add(root)
        self.notebook = Gtk.Notebook()
        root.pack_start(self.notebook, True, True, 0)

        # A true full-size solid panel: user visually observes pixels/brightness.
        screen = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.color_area = Gtk.DrawingArea()
        self.color_area.set_size_request(500, 280)
        self.color_area.set_hexpand(True)
        self.color_area.set_vexpand(True)
        self.color_area.connect("draw", self._draw_color)
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

        keys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
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
        area = Gtk.DrawingArea()
        area.set_size_request(500, 280)
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        area.connect("draw", self._draw_color)
        area.connect("button-press-event", self._fullscreen_click)
        win.add(area)
        win.connect("key-press-event", self._fullscreen_key)
        win.connect("destroy", self._fullscreen_closed)
        self._fullscreen, self._fullscreen_area = win, area
        win.show_all()
        win.fullscreen()

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

    def _draw_color(self, _area, cr) -> bool:
        r, g, b = PALETTE[self._color_index][1]
        cr.set_source_rgb(r, g, b)
        cr.paint()
        return True

    def _update_color(self) -> None:
        self.color_label.set_text(
            PALETTE[self._color_index][0] + " — تحقق بصريًا من عدم وجود بقع أو خطوط أو بكسلات عالقة.")
        self.color_area.queue_draw()
        if self._fullscreen_area is not None:
            self._fullscreen_area.queue_draw()

    def _next_color(self, *_args) -> None:
        self._color_index = (self._color_index + 1) % len(PALETTE)
        self._update_color()

    def _keypress(self, _widget, event) -> bool:
        self._keys.add(int(event.keyval))
        name = Gdk.keyval_name(event.keyval) or str(event.keyval)
        self.key_label.set_text("عدد رموز المفاتيح المختلفة المستقبلة: "
                                + str(len(self._keys)) + " — الأخير: " + name
                                + "\nقد يعترض مدير النوافذ بعض مفاتيح F؛ قيّمها يدويًا.")
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
                                 "distinct_key_codes": len(self._keys)},
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
        if self._camera is not None and self._camera.poll() is None:
            self._camera.terminate()
            try:
                self._camera.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._camera.kill()
