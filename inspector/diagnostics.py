"""Opt-in, read-only L2/L3 diagnostic probes.

The collector and L1 decision are deliberately untouched.  No disk writes,
SMART self-tests, firmware changes, network transmissions or privileged
operations occur here.  Tests cover *available observable capabilities*, not
a certificate that every physical component is healthy.
"""
from __future__ import annotations

import glob
from datetime import datetime, timezone
import hashlib
import os
import time
import threading
from typing import Callable

LEVELS = ("L2", "L3")
TEMPERATURE_STOP_C = 85.0
MAX_L3_SECONDS = 1800
MANUAL_TESTS = (
    ("display", "الشاشة: افتح صور ألوان كاملة وتحقق من البكسلات والإضاءة"),
    ("keyboard", "لوحة المفاتيح: اضغط جميع المفاتيح بما فيها F والأرقام"),
    ("touchpad", "لوحة اللمس: تحريك المؤشر والنقر والتمرير"),
    ("audio", "الصوت: اختبر السماعتين والميكروفون مع سماع تسجيل"),
    ("camera", "الكاميرا: تحقق من الصورة والتركيز والإضاءة"),
    ("ports", "المنافذ: أدخل ملحقًا سليمًا واختبر كل منفذ"),
    ("wireless", "Wi-Fi/Bluetooth: اختبر اتصالًا حقيقيًا بجهاز آخر"),
)


def _temperature() -> dict:
    """Read kernel thermal-zone Celsius measurements without writing controls."""
    values = []
    for filename in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(filename, encoding="ascii") as stream:
                raw = stream.read(32).strip()
            value = int(raw) / 1000
            if -10 <= value <= 125:
                values.append(round(value, 1))
        except (OSError, ValueError):
            continue
    return {"status": "observed" if values else "unknown",
            "max_c": max(values) if values else None,
            "readings_c": values}


def _cpu(cancel: threading.Event, *, seconds: float, on_tick=None) -> dict:
    """Bounded reproducible SHA-256 workload; not a CPU defect certification."""
    start = time.monotonic()
    target = min(max(float(seconds), 0.05), MAX_L3_SECONDS)
    if target > 60 and _temperature()["max_c"] is None:
        return {"status": "unavailable", "reason":
                "يُرفض ضغط طويل لأن قراءة الحرارة غير متاحة؛ استعمل اختبارًا أقصر."}
    known = hashlib.sha256(b"abc").hexdigest()
    if known != ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"):
        return {"status": "fail", "reason": "مرجع SHA-256 غير صحيح"}
    iterations = 0
    last_tick = start
    peak = None
    block = b"PCInspector-L2-L3" * 4096
    while time.monotonic() - start < target:
        if cancel.is_set():
            return {"status": "cancelled", "iterations": iterations,
                    "max_temperature_c": peak}
        for _ in range(32):
            hashlib.sha256(block).digest()
        iterations += 32
        if iterations % 256 == 0:
            thermal = _temperature()
            value = thermal.get("max_c")
            if value is not None:
                peak = value if peak is None else max(peak, value)
            if value is None and target > 60:
                return {"status": "temperature_monitor_lost",
                        "reason": "انقطعت قراءة الحرارة؛ أوقف اختبار الضغط احترازيًا.",
                        "iterations": iterations, "max_temperature_c": peak}
            if value is not None and value >= TEMPERATURE_STOP_C:
                return {"status": "stopped_heat", "iterations": iterations,
                        "max_temperature_c": peak}
            now = time.monotonic()
            if on_tick is not None and now - last_tick >= 1:
                on_tick({"elapsed_seconds": round(now-start, 1),
                         "target_seconds": target,
                         "thermal_max_c": value, "thermal_peak_c": peak})
                last_tick = now
    return {"status": "pass_limited", "iterations": iterations,
            "duration_seconds": round(time.monotonic()-start, 3),
            "max_temperature_c": peak,
            "limitation": "اجتاز الحساب المحدود، لا يثبت الاستقرار طويل المدى"}


def _ram(cancel: threading.Event, mib: int) -> dict:
    """Test one temporary allocated buffer, not all RAM or individual DIMMs."""
    mib = max(1, min(int(mib), 128))
    n = mib * 1024 * 1024
    try:
        buf = bytearray(n)
        for pattern in (0x00, 0xAA, 0x55, 0xFF):
            if cancel.is_set():
                return {"status": "cancelled"}
            # Slice assignment avoids an expensive per-byte Python loop.
            buf[:] = bytes([pattern]) * n
            if any(v != pattern for v in buf):
                return {"status": "fail", "pattern": pattern}
        return {"status": "pass_limited", "tested_mib": mib,
                "limitation": "فحص مخزن ذاكرة محجوز؛ لا يغطي RAM كاملة"}
    except MemoryError:
        return {"status": "unavailable", "reason": "تعذر حجز الذاكرة المطلوبة"}


def _peripheral_inventory() -> dict:
    """Presence alone is not a health test; mark all unresolved evidence."""
    def paths(pattern: str) -> list[str]:
        return sorted(glob.glob(pattern))[:32]
    return {
        "status": "inventory_only",
        "video_nodes": paths("/dev/video[0-9]*"),
        "audio_cards": paths("/proc/asound/card[0-9]*"),
        "input_devices": paths("/dev/input/event[0-9]*"),
        "usb_devices": paths("/sys/bus/usb/devices/[0-9]*"),
        "network_interfaces": sorted(
            x for x in os.listdir("/sys/class/net")
            if x != "lo") if os.path.isdir("/sys/class/net") else [],
        "limitation": "المكوّن المكتشف لم يُختبر أداؤه ولا اتصاله",
    }


def run_level(level: str, progress: Callable[[dict], None] | None = None,
              cancel: threading.Event | None = None,
              *, cpu_seconds: float | None = None) -> dict:
    """Run one explicit L2 or L3 session, with bounded CPU/RAM usage.

    Only the caller starts a level; never starts during L1 or on phone connect.
    Cancellation is cooperative; progress events are emitted after each probe.
    """
    if level not in LEVELS:
        raise ValueError("unsupported diagnostic level")
    cancel = cancel or threading.Event()
    started = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    events = {}
    tasks = [
        ("peripherals", lambda: _peripheral_inventory()),
        ("temperature_before", _temperature),
        ("cpu", lambda: _cpu(
            cancel,
            seconds=cpu_seconds if cpu_seconds is not None
                    else (1.0 if level == "L2" else 900.0),
            on_tick=(lambda data: progress({"level": level, "step": "cpu_progress",
                                           "result": data}) if progress else None))),
        ("memory", lambda: _ram(cancel, 16 if level == "L2" else 64)),
        ("temperature_after", _temperature),
    ]
    for name, probe in tasks:
        if cancel.is_set():
            break
        try:
            value = probe()
        except (OSError, ValueError, RuntimeError) as exc:
            value = {"status": "execution_error", "reason": str(exc)[:180]}
        events[name] = value
        if progress:
            progress({"level": level, "step": name, "result": value})
        if value.get("status") in ("stopped_heat", "cancelled", "temperature_monitor_lost"):
            cancel.set()
            break
    return {
        "level": level, "status": "cancelled" if cancel.is_set() else "complete",
        "started_utc": started_utc,
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "results": events,
        "manual_tests": [
            {"id": ident, "instruction": message, "status": "not_tested"}
            for ident, message in MANUAL_TESTS
        ],
        "limitations": ("تقييم تشخيصي محدود وغير شامل؛ لا كتابة على الأقراص الداخلية؛ "
                        "المكونات التي تتطلب اختبارًا تفاعليًا لا تُعد سليمة تلقائيًا."),
    }
