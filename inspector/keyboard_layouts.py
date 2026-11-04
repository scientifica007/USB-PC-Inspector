"""Reversible, explicit X11 keyboard layout selection for the interactive test.

Reference selection is read-only; applying a layout requires a separate click.
No persistent files or system-wide keyboard configuration are changed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

# XKB 'dz(ar)' is Arabic (Algeria). Bare 'dz' is Berber, not Arabic.
LAYOUTS = {
    "us": ("QWERTY — English (US)", "us", "",
           "Q W E R T Y U I O P\nA S D F G H J K L\nZ X C V B N M"),
    "fr": ("AZERTY — Français", "fr", "",
           "A Z E R T Y U I O P\nQ S D F G H J K L M\nW X C V B N"),
    "dz_ar": ("العربية (الجزائر) — Arabic (Algeria)", "dz", "ar",
              "المرجع XKB: dz(ar). تختلف الرموز المطبوعة باختلاف لوحة الجهاز."),
}
_SAFE = re.compile(r"^[a-zA-Z0-9_,.:+-]*$")


def parse_xkb_query(output: str) -> dict[str, str]:
    """Read a snapshot while rejecting unexpected parameter strings."""
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        if key in ("rules", "model", "layout", "variant", "options"):
            if not _SAFE.fullmatch(value):
                raise ValueError("تعريف غير صالح لإعدادات لوحة المفاتيح الأصلية")
            values[key] = value
    if not values.get("layout"):
        raise ValueError("لم يمكن قراءة التخطيط السابق")
    return values


def xkb_arguments(layout: str, variant: str = "", options: str = "",
                  model: str = "") -> list[str]:
    """Use argument arrays, never a shell; clear old options before restoring."""
    for value in (layout, variant, options, model):
        if not _SAFE.fullmatch(value):
            raise ValueError("قيمة XKB غير مدعومة")
    args = ["setxkbmap", "-layout", layout, "-variant", variant, "-option", ""]
    if model:
        args.extend(["-model", model])
    if options:
        args.extend(["-option", options])
    return args


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True,
                            timeout=6, check=False)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip()[:220]
                           or "تعذر تطبيق التخطيط")
    return result.stdout


def read_x11_layout() -> dict[str, str]:
    if (not os.environ.get("DISPLAY")
            or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
            or os.environ.get("WAYLAND_DISPLAY")):
        raise RuntimeError("تغيير XKB المؤقت متاح داخل جلسة X11 فقط")
    if not shutil.which("setxkbmap"):
        raise RuntimeError("الأداة setxkbmap غير مثبتة في جلسة Live")
    return parse_xkb_query(_run(["setxkbmap", "-query"]))


def apply_test_layout(layout_id: str,
                      original: dict[str, str] | None = None) -> dict[str, str]:
    if layout_id not in LAYOUTS:
        raise ValueError("التخطيط غير مدعوم")
    current = read_x11_layout()
    original = current if original is None else original
    _, layout, variant, _ = LAYOUTS[layout_id]
    _run(xkb_arguments(layout, variant, current.get("options", ""),
                       current.get("model", "")))
    return original


def restore_x11_layout(original: dict[str, str] | None) -> None:
    if original is None:
        return
    _run(xkb_arguments(original["layout"], original.get("variant", ""),
                       original.get("options", ""), original.get("model", "")))
