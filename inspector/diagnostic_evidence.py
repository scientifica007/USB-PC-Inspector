"""Conservative derived view of L2/L3 and human observations.

This layer never edits raw L1, its SMART measurements, or the purchase verdict.
A passing limited probe is not a hardware-health certification.
"""
from __future__ import annotations

from typing import Any

LABELS = {
    "cpu": "المعالج CPU",
    "memory": "الذاكرة RAM",
    "screen": "الشاشة",
    "keyboard": "لوحة المفاتيح",
    "pointer": "لوحة اللمس / المؤشر",
    "speaker": "السماعات",
    "microphone": "الميكروفون",
    "camera": "الكاميرا",
}
STATUS_LABELS = {
    "not_tested": "لم يُختبر",
    "limited_pass": "اجتاز اختبارًا محدودًا",
    "reported_pass": "نجح وفق ملاحظة المستخدم",
    "reported_fail": "سُجلت مشكلة وفق ملاحظة المستخدم",
    "inconclusive": "النتيجة غير حاسمة",
    "needs_confirmation": "أُجريت محاولة؛ يلزم تأكيد النتيجة",
    "probe_failed": "فشل اختبار تقني أو أوقفته الحماية",
}
RATING_TO_STATUS = {
    "pass": "reported_pass",
    "fail": "reported_fail",
    "inconclusive": "inconclusive",
    "not_tested": "not_tested",
}
AUTOMATED = {"cpu": "cpu", "memory": "memory"}


def build_diagnostic_review(report: dict[str, Any],
                            sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build explicit component evidence; never turn 'attempted' into a pass."""
    components = {
        name: {"id": name, "name": label, "status": "not_tested",
               "label": STATUS_LABELS["not_tested"], "evidence": "",
               "source": ""}
        for name, label in LABELS.items()
    }
    seen = 0
    for session in sessions[:200]:
        if not isinstance(session, dict):
            continue
        seen += 1
        level = session.get("level")
        results = session.get("results")
        if not isinstance(results, dict):
            continue
        if level in ("L2", "L3"):
            for name, field in AUTOMATED.items():
                probe = results.get(field)
                if not isinstance(probe, dict):
                    continue
                status = probe.get("status")
                if status == "pass_limited":
                    # Never erase an earlier recorded fault with a later success.
                    if components[name]["status"] != "probe_failed":
                        seconds = probe.get("duration_seconds") if name == "cpu" else None
                        size = probe.get("tested_mib") if name == "memory" else None
                        detail = (f"؛ {seconds} ثانية" if isinstance(seconds, (int, float))
                                  else f"؛ {size} MiB" if isinstance(size, int) else "")
                        components[name].update(
                            status="limited_pass", label=STATUS_LABELS["limited_pass"],
                            evidence=f"{level}: اختبار ناجح ضمن حدوده{detail}",
                            source="automated_limited",
                        )
                elif status in ("fail", "stopped_heat", "execution_error",
                                "temperature_monitor_lost"):
                    components[name].update(
                        status="probe_failed", label=STATUS_LABELS["probe_failed"],
                        evidence=f"{level}: {status}", source="automated_limited",
                    )
                elif status in ("cancelled", "unavailable") and components[name]["status"] == "not_tested":
                    components[name].update(
                        status="inconclusive", label=STATUS_LABELS["inconclusive"],
                        evidence=f"{level}: {status}", source="automated_limited",
                    )
        elif level == "interactive":
            user_ratings = session.get("user_verdicts")
            if not isinstance(user_ratings, dict):
                user_ratings = {}
            for name in ("screen", "keyboard", "pointer", "speaker",
                         "microphone", "camera"):
                value = results.get(name)
                if not isinstance(value, dict):
                    continue
                rating = user_ratings.get(name)
                if isinstance(rating, dict):
                    choice = rating.get("status")
                    note = rating.get("note", "")
                    if choice in RATING_TO_STATUS and choice != "not_tested":
                        status = RATING_TO_STATUS[choice]
                        components[name].update(
                            status=status, label=STATUS_LABELS[status],
                            evidence=str(note)[:300] if note else "تقييم صريح من المستخدم",
                            source="user_observation",
                        )
                        continue
                # Legacy 0.2.0 results have only attempted/observed signals.
                if components[name]["status"] == "not_tested" and value.get("status") not in (None, "not_tested"):
                    components[name].update(
                        status="needs_confirmation",
                        label=STATUS_LABELS["needs_confirmation"],
                        evidence="أحداث أو محاولة تشغيل دون حكم بصري/سمعي",
                        source="attempt_only",
                    )
    return {
        "version": 1,
        "session_count": seen,
        "components": list(components.values()),
        "purchase_verdict": (report.get("purchase_assessment") or {}).get("verdict"),
        "scope": ("نتائج مشتقة من الفحوص الإضافية؛ لا تغير حقيقة SMART أو حكم شراء L1. "
                  "الاختبارات المحدودة ليست شهادة سلامة. أحكام المستخدم ذاتية وموسومة."),
    }


def diagnostic_review_text(review: dict[str, Any]) -> str:
    lines = ["نتائج الفحوص الإضافية — تقييم محدد بالأدلة", ""]
    for component in review.get("components", []):
        if not isinstance(component, dict):
            continue
        title = str(component.get("name", "?"))
        status = str(component.get("label", STATUS_LABELS["not_tested"]))
        evidence = str(component.get("evidence", "")).strip()
        lines.append("• " + title + ": " + status +
                     (" — " + evidence if evidence else ""))
    lines.extend(["", str(review.get("scope", ""))])
    return "\n".join(lines)
