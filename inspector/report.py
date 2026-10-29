"""Produce offline HTML reports with escaped values and no external dependencies."""
from __future__ import annotations
import datetime as dt
import html
import json
from typing import Any


def display(value: Any) -> str:
    if value is None:
        return "غير متاح"
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def make_html(report: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(display(value), quote=True)

    def table(title: str, fields: dict[str, Any]) -> str:
        rows = "".join("<tr><th>" + esc(k) + "</th><td>" + esc(v) + "</td></tr>"
                       for k, v in fields.items())
        return "<section><h2>" + esc(title) + "</h2><table>" + rows + "</table></section>"

    findings = "".join(
        '<article class="' + esc(x.get("level")) + '"><b>' + esc(x.get("code")) +
        "</b> — " + esc(x.get("message")) + "</article>"
        for x in report.get("findings", [])
    )
    bios = dict(report.get("bios") or {})
    raw_date = bios.get("bios_date")
    if isinstance(raw_date, str):
        try:
            bios["bios_date"] = dt.datetime.strptime(raw_date, "%m/%d/%Y").strftime("%d/%m/%Y")
        except ValueError:
            pass
    content = table("النظام والـ BIOS", bios)
    content += table("المعالج", report.get("cpu", {}))
    content += table("الذاكرة", report.get("memory", {}))
    for disk in report.get("storage", []):
        content += table("وحدة التخزين " + display(disk.get("path")),
                         {**{k: v for k, v in disk.items() if k != "smart"},
                          **{"smart_" + k: v for k, v in disk.get("smart", {}).items()}})
    for batt in report.get("battery", []):
        content += table("البطارية", batt)
    return (
        '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>PC Inspector — تقرير تشخيص</title>'
        '<style>body{font:16px/1.7 system-ui,"Noto Sans",sans-serif;margin:auto;'
        'max-width:980px;padding:24px;color:#142235;background:#f7f9fc}'
        'h1{color:#162e4e}section{margin:20px 0;background:white;padding:16px;'
        'border:1px solid #dfe5eb;border-radius:12px}table{width:100%;border-collapse:collapse}'
        'td,th{padding:8px;text-align:right;border-bottom:1px solid #edf0f3;'
        'vertical-align:top;overflow-wrap:anywhere}th{width:36%;color:#43566d}'
        'article{padding:12px;background:#edf2f8;border-right:4px solid #6984a6;margin:8px 0}'
        'article.warning{border-color:#cf7334;background:#fff2e5}'
        'article.unknown{border-color:#999}small{color:#52657c}'
        '@media print{body{background:white}section{break-inside:avoid}}</style></head><body>'
        '<h1>PC Inspector — تقرير فحص أولي</h1><small>الوقت UTC: ' +
        esc(report.get("created_utc")) + '</small><p><strong>تنبيه:</strong> '
        'عدم ظهور تحذيرات لا يثبت خلو الحاسوب من العيوب. لم يُنفذ تعديل BIOS '
        'أو فحص شامل للذاكرة أو اختبار إجهاد.</p><h2>الملاحظات التشخيصية</h2>' +
        findings + content + '</body></html>'
    )
