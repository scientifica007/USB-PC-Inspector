"""Optional human-assisted component checks; never claim hardware certification.

Screen colours, keyboard input, pointer and speaker/microphone use the running
Live environment. No internal-drive writes, automatic camera capture, or
remote activation. User observations remain explicitly tagged as subjective.
"""
from __future__ import annotations

import math
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
        self.color_area.connect("draw", self._draw_color)
        screen.pack_start(self.color_area, True, True, 0)
        self.color_label = Gtk.Label()
        screen.pack_start(self.color_label, False, False, 0)
        next_color = Gtk.Button(label="اللون التالي")
        next_color.connect("clicked", self._next_color)
        screen.pack_start(next_color, False, False, 0)
        self.notebook.append_page(screen, Gtk.Label(label="الشاشة"))
        self._update_color()

        keys = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.key_label = Gtk.Label(label="اضغط مفاتيح مختلفة داخل هذه النافذة ثم قيّمها بنفسك.")
        keys.pack_start(self.key_label, False, False, 0)
        keys.connect("key-press-event", self._keypress)
        self.connect("key-press-event", self._keypress)
        self.notebook.append_page(keys, Gtk.Label(label="لوحة المفاتيح"))

        pointer = Gtk.EventBox()
        pointer.set_visible_window(True)
        pointer.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.pointer_label = Gtk.Label(label="حرّك المؤشر هنا وانقر؛ جرب لوحة اللمس نفسها لا فأرة خارجية.")
        pointer.add(self.pointer_label)
        pointer.connect("motion-notify-event", self._motion)
        pointer.connect("button-press-event", self._click)
        self.notebook.append_page(pointer, Gtk.Label(label="لوحة اللمس"))

        audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.audio_label = Gtk.Label(label="الصوت يحتاج تأكيدك السمعي؛ التسجيل يبقى في RAM ولا يُحفَظ.")
        audio.pack_start(self.audio_label, False, False, 0)
        play = Gtk.Button(label="تشغيل نغمة السماعة")
        record = Gtk.Button(label="تسجيل 3 ثوانٍ ثم سماع الميكروفون")
        play.connect("clicked", lambda *_: self._audio_job("play"))
        record.connect("clicked", lambda *_: self._audio_job("record"))
        audio.pack_start(play, False, False, 0)
        audio.pack_start(record, False, False, 0)
        self.notebook.append_page(audio, Gtk.Label(label="الصوت والميكروفون"))

        camera = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.camera_label = Gtk.Label(label="اختبار كاميرا اختياري؛ لا يحتفظ بصور أو فيديو.")
        open_cam = Gtk.Button(label="عرض الكاميرا محليًا")
        open_cam.connect("clicked", self._open_camera)
        camera.pack_start(self.camera_label, False, False, 0)
        camera.pack_start(open_cam, False, False, 0)
        self.notebook.append_page(camera, Gtk.Label(label="الكاميرا"))

        root.pack_start(Gtk.Label(label="هذه اختبارات تفاعلية محدودة؛ نجاحها لا يثبت خلو القطع من العيوب الكامنة."), False, False, 0)
        done = Gtk.Button(label="تسجيل ملاحظات الاختبار وإغلاق")
        done.connect("clicked", self._finish)
        root.pack_start(done, False, False, 0)

    def _draw_color(self, _area, cr) -> bool:
        r, g, b = PALETTE[self._color_index][1]
        cr.set_source_rgb(r, g, b)
        cr.paint()
        return False

    def _update_color(self) -> None:
        self.color_label.set_text(
            PALETTE[self._color_index][0] + " — تحقق بصريًا من عدم وجود بقع أو خطوط أو بكسلات عالقة.")
        self.color_area.queue_draw()

    def _next_color(self, *_args) -> None:
        self._color_index = (self._color_index + 1) % len(PALETTE)
        self._update_color()

    def _keypress(self, _widget, event) -> bool:
        if event.keyval not in (Gdk.KEY_Escape,):
            self._keys.add(int(event.keyval))
            self.key_label.set_text("عدد رموز المفاتيح المختلفة المستقبلة: " + str(len(self._keys)))
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
    def _tone() -> bytes:
        return b"".join(
            struct.pack("<h", int(0.18 * 32767 * math.sin(2*math.pi*440*i/16000)))
            for i in range(16000))

    def _audio_job(self, mode):
        def work():
            try:
                if not shutil.which("aplay"):
                    raise RuntimeError("aplay غير متوفر")
                if mode == "play":
                    sound = self._tone()
                else:
                    if not shutil.which("arecord"):
                        raise RuntimeError("arecord غير متوفر")
                    r = subprocess.run(["arecord", "-q", "-d", "3", "-t", "raw",
                                        "-f", "S16_LE", "-r", "16000", "-c", "1"],
                                       capture_output=True, timeout=8, check=False)
                    if r.returncode:
                        raise RuntimeError("تعذر تسجيل الصوت: " + r.stderr.decode(errors="replace")[-120:])
                    sound = r.stdout
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
        threading.Thread(target=work, daemon=True).start()

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
        self._camera = subprocess.Popen(
            ["gst-launch-1.0", "-q", "v4l2src", "device=/dev/video0",
             "!", "videoconvert", "!", "autovideosink"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.camera_label.set_text("نافذة معاينة الكاميرا مفتوحة؛ افحص الصورة وأغلق النافذة عند الانتهاء.")

    def _finish(self, *_args):
        if self._on_result is not None:
            self._on_result({
                "level": "interactive",
                "status": "user_assisted_partial",
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
                "limitations": "إشارات جزئية وتقييم بصري/سمعي من المستخدم؛ لا شهادة سلامة.",
            })
        self.destroy()

    def _clean_up(self, *_args):
        if self._camera is not None and self._camera.poll() is None:
            self._camera.terminate()
            try:
                self._camera.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._camera.kill()
