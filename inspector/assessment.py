"""Deterministic preliminary purchase guidance; never certifies device health.

This module consumes the existing v1 report without changing collectors.
"""
from __future__ import annotations

from typing import Any


def assess(report: dict[str, Any]) -> dict[str, Any]:
    """Conservative L1 recommendation based only on observed evidence."""
    findings = report.get("findings")
    if not isinstance(findings, list):
        findings = []
    codes = [f.get("code") for f in findings if isinstance(f, dict)]
    storage = report.get("storage")
    if not isinstance(storage, list):
        storage = []
    unknown = bool(report.get("disk_probe_error")) or "disk_scan_unavailable" in codes or "smart_read_incomplete" in codes
    unknown = unknown or any(
        not isinstance(d, dict)
        or not isinstance(d.get("smart"), dict)
        or d["smart"].get("status") in ("unavailable", "not_tested", None)
        for d in storage
    )
    critical = "smart_failed" in codes or "smart_critical_exit" in codes
    warnings = [f for f in findings if isinstance(f, dict) and f.get("level") == "warning"]
    if critical:
        verdict, reason = "do_not_buy", "أبلغ قرص داخلي عن إخفاق SMART؛ لا يُنصح بالشراء قبل التحقق الفني."
    elif warnings:
        verdict, reason = "inspect_before_payment", "ظهرت تحذيرات تستدعي فحصًا إضافيًا قبل الدفع."
    elif unknown or not storage:
        verdict, reason = "undetermined", "بيانات التخزين غير كافية لاتخاذ قرار شراء."
    else:
        verdict, reason = "inspect_before_payment", "لا توجد أدلة كافية لإثبات سلامة الجهاز؛ يلزم فحص إضافي."
    return {
        "level": "L1",
        "verdict": verdict,
        "reason": reason,
        "evidence_codes": [c for c in codes if isinstance(c, str)],
        "limitations": [
            "هذا تقييم أولي لا يثبت سلامة الجهاز.",
            "لم تُقيّم مطابقة الإعلان أو السعر أو الضمان أو ملاءمة الاستخدام.",
        ],
        "price_assessed": False,
    }
