"""Offline Arabic HTML report: evidence first, detailed SMART on demand.

All firmware strings and report values are escaped. No scripts, network assets,
writes, or changes to the JSON report schema are introduced here.
"""
from __future__ import annotations

import datetime as dt
import html
import json
from typing import Any

from .ui_model import VERDICTS, date_ar, memory_summary, memory_text


def display(value: Any) -> str:
    if value is None:
        return "غير متاح"
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def make_html(report: dict[str, Any]) -> str:
    """Create a standalone, offline, printable RTL report from completed L1 data."""
    def esc(value: Any) -> str:
        return html.escape(display(value), quote=True)

    def obj(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def table(title: str, fields: dict[str, Any]) -> str:
        rows = "".join(
            "<tr><th scope=\"row\">" + esc(key) + "</th><td>" + esc(value) + "</td></tr>"
            for key, value in fields.items()
        )
        return "<section><h2>" + esc(title) + "</h2><table>" + rows + "</table></section>"

    assessment = obj(report.get("purchase_assessment"))
    verdict = assessment.get("verdict")
    label, tone = VERDICTS.get(verdict, VERDICTS["undetermined"])
    reason = assessment.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "لا توجد بيانات تقييم كافية؛ لا يمكن استنتاج سلامة الحاسوب."
    verdict_html = (
        '<section class="verdict ' + tone + '" aria-label="نتيجة الفحص">'
        '<div class="eyebrow">خلاصة الفحص الأولي L1</div>'
        '<h2>' + esc(label) + '</h2><p>' + esc(reason) + '</p></section>'
    )

    raw_findings = report.get("findings")
    findings = [item for item in raw_findings if isinstance(item, dict)] if isinstance(raw_findings, list) else []
    evidence_items = "".join(
        '<li class="' + (item.get("level") if item.get("level") in ("info", "warning", "unknown") else "info") + '">'
        '<strong>' + esc(item.get("message") or item.get("code")) + '</strong>'
        '<span class="code">' + esc(item.get("code")) + '</span></li>'
        for item in findings
    )
    if not evidence_items:
        evidence_items = "<li>لا توجد أدلة تشخيصية مدرجة؛ لا يعني ذلك سلامة الجهاز.</li>"
    evidence_html = '<section><h2>الأدلة والتحذيرات</h2><ul class="evidence">' + evidence_items + '</ul></section>'

    bios = dict(obj(report.get("bios")))
    raw_date = bios.get("bios_date")
    if isinstance(raw_date, str):
        try:
            bios["bios_date"] = dt.datetime.strptime(raw_date, "%m/%d/%Y").strftime("%d/%m/%Y")
        except ValueError:
            pass
    cpu = obj(report.get("cpu"))
    memory = obj(report.get("memory"))
    slots = memory.get("slots")
    memory_fields = {
        "سعة الذاكرة المركبة": memory_summary(memory).get("installed"),
        "الذاكرة التي يراها Linux": memory_text(memory.get("total_bytes")),
        "وحدات الذاكرة (DMI)": slots if isinstance(slots, list) else None,
    }

    storage = report.get("storage")
    disks = [item for item in storage if isinstance(item, dict)] if isinstance(storage, list) else []
    disk_parts = []
    for disk in disks:
        smart = obj(disk.get("smart"))
        exit_info = obj(smart.get("smartctl_exit"))
        health = smart.get("overall_passed")
        if health is False:
            health_label = "إخفاق SMART مسجل"
        elif exit_info.get("critical") is True:
            health_label = "مؤشر إخفاق SMART حرج"
        elif health is True and smart.get("status") == "reported":
            health_label = "لم يُبلَّغ عن إخفاق حالي؛ ليست شهادة سلامة"
        else:
            health_label = "النتيجة غير محسومة"
        diagnostic = obj(smart.get("diagnostic_evidence"))
        attr_info = obj(diagnostic.get("ata_smart_attributes"))
        attributes = attr_info.get("table")
        failed_attributes = []
        if isinstance(attributes, list):
            for attribute in attributes:
                if isinstance(attribute, dict) and attribute.get("when_failed") == "now":
                    failed_attributes.append(str(attribute.get("name") or attribute.get("id")))
        errors_info = obj(obj(diagnostic.get("ata_smart_error_log")).get("summary"))
        capacity = disk.get("size_bytes")
        capacity_label = (f"{capacity / 1_000_000_000:.0f} GB"
                          if type(capacity) is int and capacity > 0 else None)
        basic = {
            "المسار": disk.get("path"),
            "طراز القرص": disk.get("model"),
            "السعة": capacity_label,
            "السعة الدقيقة (بايت)": capacity,
            "الناقل": disk.get("transport"),
            "حالة SMART": health_label,
            "اكتمال قراءة SMART": smart.get("status"),
            "خطأ القراءة": smart.get("read_warning"),
            "رمز smartctl": exit_info.get("code"),
            "خطأ تنفيذ/قراءة": exit_info.get("read_failure"),
            "سمات SMART تحت العتبة حاليًا": ", ".join(failed_attributes) or None,
            "عدد أخطاء سجل SMART (تراكمية)": errors_info.get("count"),
            "ساعات التشغيل": smart.get("power_on_hours"),
            "درجة الحرارة (°C)": smart.get("temperature_c"),
        }
        disk_parts.append(table("التخزين الداخلي", basic))
        if diagnostic:
            pretty = json.dumps(diagnostic, ensure_ascii=False, indent=2)
            disk_parts.append(
                '<details class="technical"><summary>تفاصيل SMART الفنية (حقول مختارة)</summary>'
                '<p>تُعرض هذه التفاصيل للمتخصصين؛ ولا تغير خلاصة الفحص أعلاه.</p>'
                '<pre dir="ltr">' + esc(pretty) + '</pre></details>'
            )
    if not disk_parts:
        disk_parts.append('<section><h2>التخزين الداخلي</h2><p>'
                          'لم تُعرض أقراص داخلية في التقرير؛ لا يُعد ذلك إثباتًا لعدم وجودها.'
                          '</p></section>')

    batteries = report.get("battery")
    if not isinstance(batteries, list) or not batteries:
        battery_html = ('<section><h2>البطارية</h2><p>لم تتوفر بيانات عن البطارية؛ '
                        'لا يمكن الجزم بوجودها أو حالتها من هذا الفحص وحده.</p></section>')
    else:
        battery_html = "".join(
            table("البطارية", item) for item in batteries if isinstance(item, dict)
        )

    limitations = assessment.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        limitations = ["هذا فحص أولي وليس شهادة سلامة أو تقييمًا للسعر والضمان."]
    limitations_html = "<ul>" + "".join(
        "<li>" + esc(line) + "</li>" for line in limitations if isinstance(line, str)
    ) + "</ul>"
    time_text = date_ar(report.get("created_utc"))
    duration = obj(report.get("scan_timing")).get("total_seconds")
    duration_text = f"{duration:.2f} ثانية" if type(duration) in (int, float) and duration >= 0 else "غير متاح"
    summary_html = (
        '<section><h2>ملخص الجهاز</h2><div class="summary-grid">'
        '<div><span>الجهاز</span><strong>' + esc(bios.get("model")) + '</strong></div>'
        '<div><span>المعالج</span><strong>' + esc(cpu.get("model")) + '</strong></div>'
        '<div><span>الذاكرة المركبة</span><strong>' + esc(memory_summary(memory).get("installed")) + '</strong></div>'
        '<div><span>يراها Linux</span><strong>' + esc(memory_text(memory.get("total_bytes"))) + '</strong></div>'
        '<div><span>زمن جمع L1</span><strong>' + esc(duration_text) + '</strong></div>'
        '</div><small>زمن جمع البيانات لا يشمل إقلاع USB. '
        'لا يُعد فحص L1 اختبار إجهاد أو اختبارًا كاملًا للذاكرة.</small></section>'
    )

    content = (
        verdict_html + evidence_html + summary_html
        + table("النظام والـ BIOS", bios)
        + table("المعالج", cpu)
        + table("الذاكرة", memory_fields)
        + "".join(disk_parts) + battery_html
        + '<section><h2>حدود التقييم</h2>' + limitations_html + '</section>'
    )
    return (
        '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>USB PC Inspector — تقرير الفحص الأولي</title>'
        '<style>'
        'body{font:16px/1.75 system-ui,"Noto Sans Arabic",sans-serif;margin:auto;'
        'max-width:1000px;padding:20px;color:#192b43;background:#f4f6fa}'
        'main{max-width:100%}h1{margin-bottom:4px;font-size:27px}h2{font-size:19px}'
        'section,details{margin:16px 0;background:#fff;padding:16px 20px;'
        'border:1px solid #dce3ed;border-radius:12px}'
        'table{width:100%;border-collapse:collapse;table-layout:fixed}'
        'td,th{padding:9px;text-align:right;border-bottom:1px solid #e8edf4;'
        'vertical-align:top;overflow-wrap:anywhere}th{width:36%;color:#41536b}'
        '.verdict{border-right:6px solid #6984a6;background:#f0f4f9}'
        '.verdict.danger{border-color:#b94f49;background:#fff1f0}'
        '.verdict.warning{border-color:#ac7b2f;background:#fff8e9}'
        '.verdict.candidate{border-color:#486a8b;background:#eef4fb}'
        '.verdict h2{font-size:25px;margin:4px 0}'
        '.eyebrow{font-size:13px;color:#43566e;font-weight:600}'
        '.evidence{padding-right:22px}.evidence li{margin:10px 0}'
        '.evidence li.warning{border-right:3px solid #b94f49;padding-right:10px}'
        '.evidence li.unknown{border-right:3px solid #8b8e99;padding-right:10px}'
        '.code{display:block;font-size:12px;color:#67758a;direction:ltr;text-align:right}'
        '.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}'
        '.summary-grid div{padding:10px;border:1px solid #e0e7f1;border-radius:8px}'
        '.summary-grid span{display:block;font-size:12px;color:#56677d}'
        '.summary-grid strong{display:block;overflow-wrap:anywhere}'
        'small{color:#52657c}details summary{cursor:pointer;font-weight:bold}'
        'pre{direction:ltr;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;'
        'background:#f6f8fb;border-radius:8px;padding:12px;font:12px/1.5 monospace}'
        '@media(max-width:640px){body{padding:10px;font-size:14px}'
        '.summary-grid{grid-template-columns:1fr}section,details{padding:12px}'
        'th{width:38%}}@media print{body{background:#fff}'
        'section,details{break-inside:avoid}details{display:none}}'
        '</style></head><body><main><h1>USB PC Inspector</h1>'
        '<small>تقرير فحص أولي — الوقت: ' + esc(time_text) + '</small>'
        '<p>القرار مبدئي ومقيد بالأدلة؛ لا يثبت خلو الجهاز من عيوب لم تُفحص.</p>'
        + content + '</main></body></html>'
    )
