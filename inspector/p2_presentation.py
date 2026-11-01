"""Pure, optional P2 presentation and export snapshot.

A profile changes only the personal layer. Original collected report is never
mutated; default users receive the exact same report structure as before.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .p2_profiles import evaluate_purchase_profile, validate_offer, validate_profile

AXIS_LABELS = {
    "technical_safety": "السلامة التقنية",
    "hardware_requirements": "مطابقة متطلبات العتاد",
    "workload_fit": "ملاءمة مجالات العمل",
    "seller_claims": "مطابقة إعلان البائع",
    "economics": "الميزانية والضمان",
}
STATUS_LABELS = {
    "fail": "غير مستوفى",
    "needs_verification": "يلزم التحقق",
    "conditional": "مناسب بشروط",
    "pass": "مطابق للشرط المحدد فقط",
    "not_assessed": "لم يُقيّم",
}
VERDICT_LABELS = {
    "reject": "لا يُنصح بالشراء وفق متطلباتك",
    "inspect_before_payment": "يلزم التحقق قبل الدفع",
    "candidate_with_checks": "مرشح وفق شروطك مع فحوص إضافية",
    "not_applied": "الوضع العام — لم يطبّق ملف شخصي",
}


def make_personal_snapshot(report: dict, profile: dict | None,
                           offer: dict | None = None) -> dict:
    """On custom mode only, attach explicitly marked user assertions to a copy."""
    if not isinstance(report, dict):
        raise ValueError("Invalid report.")
    if profile is None:
        return report
    parsed = validate_profile(profile)
    seller = validate_offer({} if offer is None else offer)
    output = deepcopy(report)
    output["buyer_profile"] = parsed
    output["buyer_offer"] = seller
    output["buyer_profile_assessment"] = evaluate_purchase_profile(report, parsed, seller)
    output["buyer_profile_assessment"]["evidence_origin"] = (
        "L1 report + optional user-provided buyer profile/offer; "
        "not independent seller-claim verification or market appraisal"
    )
    return output


def personal_text(report: dict | None, profile: dict | None,
                  offer: dict | None = None) -> str:
    if profile is None:
        return ("الوضع العام مفعل. يعمل L1 دون متطلبات مسبقة أو سعر أو إنترنت.\n"
                "اختر «ملف مخصص» ثم اضغط «تطبيق المتطلبات» لتقييم شراء شخصي.")
    if report is None:
        return "فُعّل الملف المخصص؛ سيظهر تقييمه بعد اكتمال الفحص الأولي."
    result = evaluate_purchase_profile(report, profile, offer)
    lines = [
        "قرار الشراء الشخصي — مستقل عن التقرير الخام",
        f"الملف: {result['profile_name']}",
        "النتيجة: " + VERDICT_LABELS[result["personal_verdict"]],
        "الحكم العام الأصلي: " + str(result["generic_verdict"]),
        "",
    ]
    for axis_name, axis in result["axes"].items():
        lines.append(AXIS_LABELS.get(axis_name, axis_name) + ": " +
                     STATUS_LABELS.get(axis["status"], "غير محسوم"))
        for check in axis["checks"]:
            lines.append("  • " + str(check["code"]) + ": " +
                         STATUS_LABELS.get(check["status"], "غير محسوم") +
                         " — " + check["reason"])
        lines.append("")
    lines.extend([
        "بيانات السعر والضمان ومزاعم الإعلان يصرّح بها البائع أو المستخدم؛",
        "لا تُعامل كمعلومات اكتشفها الفاحص أو تحقق منها بشكل مستقل.",
        "هذه مقارنة شروط وليست نتيجة Benchmark أو تقييمًا لأسعار السوق.",
    ])
    return "\n".join(lines)
