"""Arabic offline desktop UI; scans in a background thread."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__

COLLECT_HELPER = "/usr/local/bin/pc-inspector-collect"
SAVE_HELPER = "/usr/local/bin/pc-inspector-save"


class InspectorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.report = None
        self.events: queue.Queue = queue.Queue()
        root.title("USB PC Inspector — فحص الحواسيب")
        root.geometry("1000x700")
        root.minsize(720, 510)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Noto Sans", 11))
        style.configure("TButton", padding=(13, 9))
        style.configure("TNotebook.Tab", padding=(16, 9))
        style.configure("Treeview", rowheight=29)

        header = ttk.Frame(root, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="USB PC Inspector", font=("Noto Sans", 18, "bold")
                  ).pack(side="right", anchor="e")
        ttk.Label(header, text="فحص استقصائي للعتاد — دون تعديل الأقراص الداخلية",
                  foreground="#576b7d").pack(side="left")

        actions = ttk.Frame(root, padding=(16, 6))
        actions.pack(fill="x")
        self.scan_button = ttk.Button(actions, text="بدء فحص الجهاز", command=self.scan)
        self.scan_button.pack(side="right", padx=5)
        self.save_button = ttk.Button(actions, text="حفظ التقرير على USB",
                                      command=self.save, state="disabled")
        self.save_button.pack(side="right", padx=5)
        ttk.Button(actions, text="نسخ JSON", command=self.copy_json).pack(
            side="right", padx=5)
        self.status = tk.StringVar(value="جاهز. ابدأ الفحص للحصول على تقرير.")
        ttk.Label(actions, textvariable=self.status, foreground="#4e6173"
                  ).pack(side="left", padx=8)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=12)
        self.summary = self.make_text_tab("النتيجة")
        self.details = self.make_text_tab("التقرير الفني JSON")
        self.about = self.make_text_tab("حول الفحص")
        self.write(self.about,
                   "PC Inspector " + __version__ +
                   "\n\nهذا الإصدار يجمع بيانات تعريف النظام وبعض مؤشرات صحة التخزين "
                   "والبطارية. لا يجري اختبار إجهاد أو اختبار ذاكرة كاملاً، "
                   "ولا يستطيع إثبات سلامة BIOS أو كون الجهاز جديداً.\n\n"
                   "تُستبعد أقراص USB من فحص التخزين الداخلي.\n\n"
                   "التقارير تُحفظ فقط في قسم على USB موسوم PCINSPECTOR_DATA "
                   "أو Ventoy. عدم وجود قسم مناسب يعني أن الحفظ غير متاح.\n\n"
                   "القرص الداخلي لا يُركّب ولا يُهيّأ ولا تُكتب عليه ملفات.")
        root.after(150, self.consume)

    def make_text_tab(self, label: str) -> tk.Text:
        parent = ttk.Frame(self.notebook)
        self.notebook.add(parent, text=label)
        vertical = ttk.Scrollbar(parent, orient="vertical")
        vertical.pack(side="left", fill="y")
        widget = tk.Text(
            parent, wrap="word", font=("Noto Sans", 12), padx=15, pady=12,
            yscrollcommand=vertical.set, bg="#fcfdff", fg="#12253b",
            relief="flat", spacing1=4, spacing3=5,
        )
        widget.pack(side="right", fill="both", expand=True)
        vertical.configure(command=widget.yview)
        widget.tag_configure("rtl", justify="right", rmargin=6)
        widget.configure(state="disabled")
        return widget

    @staticmethod
    def write(widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content, "rtl")
        widget.configure(state="disabled")

    def run_collect(self) -> None:
        command = [sys.executable, "-m", "inspector.core"]
        privileged = (os.path.exists(COLLECT_HELPER) and
                      shutil.which("sudo") is not None)
        if privileged:
            command = ["sudo", "-n", COLLECT_HELPER]
        result = subprocess.run(command, text=True, capture_output=True,
                                timeout=90, check=False)
        if privileged and result.returncode != 0:
            # Fail open for observational sysfs/lsblk only; flag reduced permissions.
            result = subprocess.run([sys.executable, "-m", "inspector.core"],
                                    text=True, capture_output=True,
                                    timeout=90, check=False)
            reduced = True
        else:
            reduced = not privileged
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-750:] or "تعذر تنفيذ الفحص.")
        data = json.loads(result.stdout)
        self.events.put(("scan", data, reduced))

    def scan(self) -> None:
        self.scan_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self.status.set("يجري جرد المكونات...")
        self.report = None
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        try:
            self.run_collect()
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.events.put(("error", "تعذر إكمال الفحص: " + str(exc)))

    @staticmethod
    def format_report(data: dict) -> str:
        bios = data.get("bios", {})
        cpu = data.get("cpu", {})
        memory = data.get("memory", {})
        def val(value: object) -> str:
            return "غير متاح" if value is None else str(value)
        lines = [
            "تقرير أولي — " + val(data.get("created_utc")),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "الشركة: " + val(bios.get("manufacturer")),
            "الطراز: " + val(bios.get("model")),
            "BIOS: " + val(bios.get("bios_vendor")) + " / " +
            val(bios.get("bios_version")),
            "وضع الإقلاع: " + val(bios.get("boot_mode")),
            "Secure Boot: " + val(bios.get("secure_boot")),
            "المعالج: " + val(cpu.get("model")),
            "الأنوية المنطقية: " + val(cpu.get("logical_processors")),
            "RAM (بايت): " + val(memory.get("total_bytes")),
            "",
            "الأقراص الداخلية المكتشفة: " + str(len(data.get("storage", []))),
        ]
        for disk in data.get("storage", []):
            smart = disk.get("smart", {})
            lines.extend([
                "  • " + val(disk.get("path")) + " — " + val(disk.get("model")),
                "    السعة (بايت): " + val(disk.get("size_bytes")),
                "    SMART: " + val(smart.get("status")),
                "    الساعات المسجلة: " + val(smart.get("power_on_hours")),
                "    نتيجة SMART العامة: " + val(smart.get("overall_passed")),
            ])
        for batt in data.get("battery", []):
            lines.append("البطارية " + val(batt.get("name")) +
                         " — السعة التقديرية: " +
                         val(batt.get("estimated_health_percent")) + "%")
        lines.append("\nالملاحظات التشخيصية:")
        for finding in data.get("findings", []):
            lines.append("• [" + val(finding.get("level")) + "] " +
                         val(finding.get("message")))
        lines.append("\nلا تعني النتائج الخالية من التحذيرات أن الجهاز سليم بالكامل.")
        return "\n".join(lines)

    def _save_worker(self) -> None:
        try:
            if not os.path.isfile(SAVE_HELPER):
                raise RuntimeError("مساعد حفظ USB غير موجود في هذا النظام.")
            result = subprocess.run(
                ["sudo", "-n", SAVE_HELPER],
                input=json.dumps(self.report, ensure_ascii=False),
                text=True, capture_output=True, timeout=50, check=False,
            )
            receipt = json.loads(result.stdout)
            if not receipt.get("saved"):
                raise RuntimeError(receipt.get("error") or "تعذر حفظ التقرير.")
            self.events.put(("saved", receipt))
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.events.put(("error", "لم يُحفظ التقرير: " + str(exc)))

    def save(self) -> None:
        if not self.report:
            return
        self.save_button.configure(state="disabled")
        self.status.set("يجري حفظ التقرير على قسم USB...")
        threading.Thread(target=self._save_worker, daemon=True).start()

    def copy_json(self) -> None:
        if not self.report:
            messagebox.showinfo("تنبيه", "ابدأ الفحص أولاً.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(self.report, ensure_ascii=False, indent=2))
        self.status.set("نُسخ التقرير إلى الحافظة.")

    def consume(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "scan":
                    data, reduced = event[1], event[2]
                    self.report = data
                    self.write(self.summary, self.format_report(data))
                    self.write(self.details, json.dumps(data, ensure_ascii=False, indent=2))
                    self.scan_button.configure(state="normal")
                    self.save_button.configure(state="normal")
                    self.status.set(
                        "اكتمل الجرد بصلاحيات محدودة؛ بعض البيانات قد تكون غير متاحة."
                        if reduced else "اكتمل الجرد. راجع النتائج قبل الشراء."
                    )
                elif event[0] == "saved":
                    self.save_button.configure(state="normal")
                    self.status.set("حُفظ التقرير: " + event[1]["json"])
                    messagebox.showinfo("نجاح", "حُفظ تقرير JSON وHTML على قسم USB.")
                else:
                    self.scan_button.configure(state="normal")
                    if self.report:
                        self.save_button.configure(state="normal")
                    self.status.set(event[1])
                    messagebox.showwarning("PC Inspector", event[1])
        except queue.Empty:
            pass
        self.root.after(150, self.consume)


def main() -> None:
    root = tk.Tk()
    InspectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
