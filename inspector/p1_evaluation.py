"""P1 conservative health and workload suitability models (no active tests).

No synthetic health percentages, no benchmark claims, and no purchase verdict
derived from suitability. The collector's facts and SMART decision stay intact.
"""
from __future__ import annotations

import re
from typing import Any


STATUS_AR = {
    "critical": "خلل حرج مثبت",
    "warning": "تحذير مدعوم بالأدلة",
    "limited": "لا إخفاق مُبلَّغ عنه في المؤشر المتاح؛ السلامة غير مثبتة",
    "not_tested": "مكتشف، لم تُختبر صحته",
    "unknown": "غير محسوم / بيانات غير كافية",
}
FIT_AR = {
    "conditional": "مناسب بشروط، دون اختبار أداء",
    "unsuitable": "دون الحد الإرشادي لهذا الاستخدام",
    "undetermined": "الملاءمة غير محسومة",
}
RULE_VERSION = "p1-heuristics-v1"
# Heuristic targets for the *specified workload class*, not benchmark scores
# or universal application minimums. No fabricated FPS/export speeds.
WORKLOADS = (
    ("office", "الأعمال المكتبية الأساسية", 4, 2, False,
     "تحرير المستندات والجداول الصغيرة والتصفح المعتدل"),
    ("remote_learning", "التعليم والتواصل المرئي الأساسي", 4, 2, False,
     "تصفح المواد التعليمية واجتماعات مصورة؛ يلزم اختبار الكاميرا والصوت والشبكة"),
    ("light_programming", "تطوير الويب والبرمجة الخفيفة", 8, 2, False,
     "محرر ومترجم ومشروعات صغيرة دون محاكاة افتراضية ثقيلة"),
    ("heavy_programming", "تطوير كبير وحاويات وآلات افتراضية", 16, 4, False,
     "مشروعات كبيرة وعدة بيئات عمل متزامنة؛ الهدف الإرشادي 16 GB وأربع وحدات منطقية"),
    ("design_2d", "الرسوم والصور ثنائية الأبعاد", 8, 2, False,
     "تحرير صور عادي؛ التصاميم الكبيرة والفلاتر GPU تحتاج تحققًا إضافيًا"),
    ("video_1080p", "مونتاج فيديو 1080p بمشروعات متعددة المسارات", 16, 4, True,
     "يلزم التحقق من تسريع GPU والترميزات والتخزين؛ ليس اختبار تصدير فيديو"),
    ("modern_gaming", "ألعاب حديثة متطلبة", 16, 4, True,
     "تتباين متطلبات الألعاب؛ الحكم النهائي يتطلب اسم اللعبة ودقة العرض واختبار GPU"),
)


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def installed_ram_gb(memory: Any) -> float | None:
    """Use DMI physical-module sizes, not Linux MemTotal or a guessed total."""
    memory = obj(memory)
    if memory.get("slots_status") != "reported":
        return None
    slots = list_of_dicts(memory.get("slots"))
    if not slots:
        return None
    total = 0.0
    for slot in slots:
        size = slot.get("size")
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|MB)\s*", size, re.I) if isinstance(size, str) else None
        if not match:
            return None
        number = float(match.group(1))
        if not 0 < number <= 1024:
            return None
        total += number if match.group(2).upper() == "GB" else number / 1024
    return round(total, 3)


def health_assessment(report: dict[str, Any]) -> dict[str, Any]:
    """Per-component findings distinguish inventory from a real health test."""
    components: list[dict[str, Any]] = []

    def add(category: str, name: str, status: str, reason: str,
            source: str, test_status: str) -> None:
        components.append({
            "category": category, "name": name[:160], "status": status,
            "label": STATUS_AR[status], "reason": reason,
            "source": source, "test_status": test_status,
        })

    cpu = obj(report.get("cpu"))
    add("cpu", str(cpu.get("model") or "المعالج"), "not_tested" if cpu.get("model") else "unknown",
        "بيانات الهوية لا تثبت سلامة المعالج أو استقراره الحراري.",
        "/proc/cpuinfo", "not_tested")
    memory = obj(report.get("memory"))
    ram_gb = installed_ram_gb(memory)
    add("memory", "الذاكرة RAM", "not_tested" if ram_gb is not None else "unknown",
        ("تم جرد الذاكرة المركبة دون فحص خلاياها أو استقرارها."
         if ram_gb is not None else "لم تكتمل بيانات سعة الذاكرة المركبة؛ لم يُجر اختبار RAM."),
        "DMI / Linux MemTotal", "not_tested")

    disks = list_of_dicts(report.get("storage"))
    if report.get("disk_probe_error"):
        add("storage", "التخزين الداخلي", "unknown",
            "تعذر جرد الأقراص الداخلية؛ عدم ظهورها لا يثبت غيابها.",
            "lsblk", "unavailable")
    elif not disks:
        add("storage", "التخزين الداخلي", "unknown",
            "لم يُكتشف قرص داخلي؛ قد يكون الجهاز دون قرص أو غير مدعوم من أداة الجرد.",
            "lsblk", "not_tested")
    for disk in disks[:32]:
        smart = obj(disk.get("smart"))
        exit_info = obj(smart.get("smartctl_exit"))
        if smart.get("overall_passed") is False or exit_info.get("critical") is True:
            status, reason = "critical", (
                "إخفاق SMART مثبت؛ يُمنع اعتبار القرص سليمًا أو مناسبًا لشراء عادي."
            )
        elif smart.get("status") == "reported" and smart.get("overall_passed") is True:
            status, reason = "limited", (
                "مؤشر SMART المتاح لا يبلّغ عن إخفاق حالي؛ هذا لا يستبعد أعطالًا أخرى."
            )
        else:
            status, reason = "unknown", (
                "القراءة أو الحكم الصحي غير مكتمل؛ لا يُفسَّر غياب الإنذار بوصفه نجاحًا."
            )
        add("storage", str(disk.get("model") or disk.get("path") or "قرص داخلي"),
            status, reason, "smartctl + lsblk",
            "smart_reported" if smart.get("status") in ("reported", "partial") else "unavailable")

    extensions = obj(report.get("hardware_extensions"))
    for category, field, name, source in (
        ("gpu", "graphics", "بطاقة الرسوميات", "PCI sysfs/lspci"),
        ("display", "displays", "الشاشة", "DRM/EDID sysfs"),
        ("network", "networks", "بطاقة الشبكة", "sysfs network"),
    ):
        items = list_of_dicts(extensions.get(field))
        if category == "display":
            items = [s for s in items if s.get("connection_status") == "connected"]
        if not items:
            add(category, name, "unknown",
                "لم تتوفر بيانات مؤكدة عن المكون؛ لا يثبت ذلك عدم وجوده.",
                source, "not_tested")
            continue
        for entry in items[:8]:
            component_name = (entry.get("description") or entry.get("connector")
                              or entry.get("interface") or name)
            add(category, str(component_name), "not_tested",
                "تم التعرف على المكون، لكن الاتصال/الأداء/الاستقرار لم تُختبر.",
                source, "not_tested")

    batteries = list_of_dicts(report.get("battery"))
    if not batteries:
        add("battery", "البطارية", "unknown",
            "لم تظهر بيانات بطارية؛ لا يُثبت ذلك وجودها أو غيابها أو حالتها الفيزيائية.",
            "sysfs power_supply", "not_tested")
    for battery in batteries[:8]:
        health = battery.get("estimated_health_percent")
        if type(health) in (int, float) and 0 <= health < 70:
            status, reason = "warning", (
                "السعة التي أبلغ عنها متحكم البطارية أقل من 70% من السعة التصميمية."
            )
        elif type(health) in (int, float) and 0 <= health <= 150:
            status, reason = "limited", (
                "نسبة السعة مقدّرة من بيانات متحكم البطارية؛ لا تكفي لتأكيد سلامة البطارية."
            )
        else:
            status, reason = "unknown", "لا تتوفر قراءة سعة موثوقة تسمح بتقييم البطارية."
        add("battery", str(battery.get("name") or "بطارية"), status, reason,
            "sysfs battery firmware", "firmware_only")

    statuses = {item["status"] for item in components}
    overall = ("critical" if "critical" in statuses
               else "warning" if "warning" in statuses
               else "unknown")
    return {
        "rule_version": RULE_VERSION, "overall": overall,
        "components": components,
        "scope": ("التعرف على مكوّن لا يثبت سلامته. لم ينفذ هذا المستوى اختبار RAM "
                  "أو GPU أو الشاشة أو الشبكة أو اختبار ضغط للمعالج."),
    }


def suitability_assessment(report: dict[str, Any]) -> dict[str, Any]:
    """Conservative, task-specific *capacity* estimates, separate from purchase."""
    cpu = obj(report.get("cpu"))
    logical = cpu.get("logical_processors")
    logical = logical if type(logical) is int and 0 < logical <= 1024 else None
    ram = installed_ram_gb(report.get("memory"))
    storage = list_of_dicts(report.get("storage"))
    rotational = any(d.get("rotational") is True for d in storage)
    health = health_assessment(report)
    critical = health["overall"] == "critical"
    results = []
    for key, title, target_ram, target_threads, needs_gpu, context in WORKLOADS:
        requirements = [
            f"هدف إرشادي لهذه الفئة: RAM ≥ {target_ram} GB، "
            f"معالجات منطقية ≥ {target_threads}. "
            "ليست حدودًا رسمية لكل برنامج."
        ]
        limitations = []
        if ram is None:
            limitations.append("سعة RAM المركبة غير مؤكدة من DMI.")
        if logical is None:
            limitations.append("عدد المعالجات المنطقية غير متاح.")
        if ram is None or logical is None:
            verdict = "undetermined"
        elif ram < target_ram or logical < target_threads:
            verdict = "unsuitable"
            if ram < target_ram:
                limitations.append(
                    f"RAM المركبة {ram:g} GB أقل من الهدف الإرشادي {target_ram} GB."
                )
            if logical < target_threads:
                limitations.append(
                    f"عدد المعالجات المنطقية {logical} أقل من الهدف {target_threads}."
                )
        elif needs_gpu:
            verdict = "undetermined"
            limitations.append("لم تُقَس قدرة GPU أو دعم الترميزات أو الأداء العملي.")
        else:
            verdict = "conditional"
            limitations.append("لم تُجر اختبارات تشغيل للتطبيقات أو قياسات أداء فعلية.")
        if rotational and key in ("light_programming", "heavy_programming", "video_1080p"):
            limitations.append("التخزين من نوع HDD؛ قد يبطئ المشروعات مقارنةً بـSSD.")
        if critical:
            limitations.append(
                "يوجد خلل تخزين حرج مثبت؛ لا يُنصح بشراء الجهاز بحالته الحالية "
                "حتى إذا كانت مواصفاته النظرية تفي بمتطلبات العمل."
            )
        results.append({
            "id": key, "name": title, "verdict": verdict, "label": FIT_AR[verdict],
            "rule_context": context, "rules": requirements,
            "reasons": limitations, "benchmark_tested": False,
            "health_blocker": critical,
        })
    return {
        "rule_version": RULE_VERSION, "workloads": results,
        "purchase_verdict_unchanged": True,
        "limitations": (
            "هذه أهداف إرشادية عامة وليست متطلبات رسمية للبرامج أو نتائج FPS/مونتاج. "
            "لم يُجر اختبار أداء. تقييم سعر الجهاز والضمان والملف الشخصي غير منفذ."
        ),
    }
