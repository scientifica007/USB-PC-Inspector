"""Pure Arabic dashboard presentation model; no GUI dependencies or I/O.

L1 previews are explicitly non-decisional. The purchase decision is read
from the completed report only and is never inferred from partial snapshots.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

VERDICTS = {
    "do_not_buy": ("لا يُنصح بالشراء", "danger"),
    "inspect_before_payment": ("يلزم الفحص قبل الدفع", "warning"),
    "undetermined": ("النتيجة غير محسومة", "neutral"),
    "candidate": ("مرشح مبدئيًا", "candidate"),
}
STAGES = {
    "identity": "هوية الجهاز والمعالج",
    "memory": "الذاكرة",
    "battery": "البطارية",
    "storage": "الأقراص الداخلية",
    "smart": "مؤشرات SMART",
}
UNKNOWN = "غير متاح"


def short(value: Any, limit: int = 120) -> str:
    if value is None or isinstance(value, (dict, list)):
        return UNKNOWN
    text = "".join(ch if ch.isprintable() else " " for ch in str(value)).strip()
    return (text[:limit] + "…") if len(text) > limit else (text or UNKNOWN)


def date_ar(timestamp: Any) -> str:
    if not isinstance(timestamp, str):
        return UNKNOWN
    try:
        return dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime(
            "%d/%m/%Y %H:%M UTC"
        )
    except ValueError:
        return UNKNOWN


def memory_text(value: Any) -> str:
    if type(value) is not int or value <= 0:
        return UNKNOWN
    return f"{value / (1024 ** 3):.1f} GiB"


def disk_text(disks: Any) -> str:
    if not isinstance(disks, list):
        return "لم يكتمل جرد الأقراص"
    if not disks:
        return "لم يُكتشف قرص داخلي"
    descriptions = []
    for disk in disks[:2]:
        if not isinstance(disk, dict):
            continue
        name = short(disk.get("model"), 45)
        size = disk.get("size_bytes")
        capacity = (f"{size / 1_000_000_000:.0f} GB"
                    if type(size) is int and size > 0 else UNKNOWN)
        descriptions.append(f"{name} — {capacity}")
    return " | ".join(descriptions) or UNKNOWN


def smart_text(disks: Any) -> str:
    if not isinstance(disks, list) or not disks:
        return "لا توجد نتائج SMART"
    states = []
    for disk in disks:
        if not isinstance(disk, dict) or not isinstance(disk.get("smart"), dict):
            states.append("قيد الفحص")
            continue
        smart = disk["smart"]
        if smart.get("overall_passed") is False:
            states.append("إخفاق مسجّل")
        elif smart.get("overall_passed") is True:
            states.append("لم يُبلّغ عن إخفاق حالي")
        elif smart.get("status") in ("unavailable", "not_tested", None):
            states.append("غير متاح")
        else:
            states.append("النتيجة غير مكتملة")
    return "، ".join(dict.fromkeys(states))


def dashboard_model(
    data: dict[str, Any] | None,
    *,
    complete: bool = False,
    stage: str | None = None,
    elapsed: float | None = None,
    reduced: bool = False,
) -> dict[str, Any]:
    """Normalize safe screen texts from a progress snapshot or final report."""
    data = data if isinstance(data, dict) else {}
    bios = data.get("bios") if isinstance(data.get("bios"), dict) else {}
    cpu = data.get("cpu") if isinstance(data.get("cpu"), dict) else {}
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    disks = data.get("storage")
    disk_count = len(disks) if isinstance(disks, list) else None
    if complete:
        assessment = data.get("purchase_assessment")
        assessment = assessment if isinstance(assessment, dict) else {}
        key = assessment.get("verdict", "undetermined")
        label, tone = VERDICTS.get(key, VERDICTS["undetermined"])
        reason = short(assessment.get("reason"), 280)
        findings = data.get("findings")
        findings = findings if isinstance(findings, list) else []
        notes = [
            short(item.get("message"), 260)
            for item in findings if isinstance(item, dict) and
            item.get("level") in ("warning", "unknown", "info")
        ]
        scan_timing = data.get("scan_timing")
        duration = (scan_timing.get("total_seconds")
                    if isinstance(scan_timing, dict) else None)
        state = "اكتمل الفحص بصلاحيات محدودة" if reduced else "اكتمل الفحص الأولي"
    else:
        label, tone = "الفحص جارٍ — لا قرار بعد", "pending"
        reason = "تظهر معلومات الجهاز تدريجيًا. لا تصدر توصية شراء قبل اكتمال الفحص."
        notes = []
        duration = elapsed
        state = ("المرحلة: " + STAGES.get(stage, "جرد المكونات")
                 if stage else "بدء الفحص الأولي")

    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
        timing = f"{duration:.2f} ثانية — دون زمن إقلاع USB"
    else:
        timing = "لم يُقَس الزمن بعد"

    battery = data.get("battery")
    if isinstance(battery, list) and battery:
        health = battery[0].get("estimated_health_percent") if isinstance(battery[0], dict) else None
        battery_text = (f"{health}% (تقدير)" if type(health) in (int, float)
                        else "بطارية مكتشفة — صحة غير محددة")
    elif isinstance(battery, list):
        battery_text = "لا توجد بيانات بطارية"
    else:
        battery_text = "قيد الفحص"

    facts = (
        ("الجهاز", short(bios.get("model") or bios.get("manufacturer"), 88)),
        ("المعالج", short(cpu.get("model"), 115)),
        ("الذاكرة RAM", memory_text(memory.get("total_bytes"))),
        ("التخزين الداخلي", disk_text(disks)),
        ("SMART", smart_text(disks)),
        ("البطارية", battery_text),
    )

    return {
        "label": label,
        "tone": tone,
        "reason": reason,
        "state": state,
        "complete": complete,
        "facts": facts,
        "disk_count": disk_count,
        "notes": notes,
        "timing": timing,
        "created": date_ar(data.get("created_utc")) if complete else "",
        "scope": "تقييم L1 أولي؛ لا يثبت سلامة الجهاز أو السعر أو الضمان.",
    }
