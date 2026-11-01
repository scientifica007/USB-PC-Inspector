"""Optional Arabic GTK buyer-profile editor, offline and no disk writes.

USB profile persistence is delegated to the narrow, privileged helper. GTK
never writes files or runs arbitrary commands. Default mode requires no setup.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from gi.repository import Gdk, GLib, Gtk, Pango

from .desktop_backend import (list_usb_profiles, load_profile_from_usb,
                              save_profile_to_usb)
from .p1_evaluation import WORKLOADS
from .p2_presentation import personal_text
from .p2_profiles import (ProfileError, dump_profile_json, load_profile_json,
                          validate_offer, validate_profile)


def _label(text: str) -> Gtk.Label:
    item = Gtk.Label(label=text)
    item.set_direction(Gtk.TextDirection.RTL)
    item.set_xalign(0.0)  # GTK mirrors xalign in RTL: physical right.
    item.set_justify(Gtk.Justification.LEFT)
    item.set_line_wrap(True)
    item.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return item


def _rtl_lines(value: str) -> str:
    return "\n".join("\u200f" + line.lstrip() if line.strip() else ""
                     for line in value.split("\n"))


class BuyerProfilePanel(Gtk.Box):
    """Main-thread widget. Workers may invoke only GLib.idle_add on completion."""

    def __init__(self, on_changed: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_border_width(12)
        self.set_direction(Gtk.TextDirection.RTL)
        self.profile: dict | None = None
        self.offer: dict = {}
        self.report: dict | None = None
        self._on_changed = on_changed
        self._busy = False

        self.pack_start(_label(
            "ملف متطلبات الشراء اختياري تمامًا. يبقى حكم L1 العام وأدلة SMART مستقلة."),
            False, False, 0)

        radio_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.general_mode = Gtk.RadioButton.new_with_label_from_widget(
            None, "الوضع العام — بلا تحضير")
        self.custom_mode = Gtk.RadioButton.new_with_label_from_widget(
            self.general_mode, "ملف متطلبات مخصص")
        radio_row.pack_start(self.general_mode, False, False, 0)
        radio_row.pack_start(self.custom_mode, False, False, 0)
        self.pack_start(radio_row, False, False, 0)

        grid = Gtk.Grid(column_spacing=14, row_spacing=8)
        grid.set_column_homogeneous(True)
        self.fields: dict[str, Gtk.Entry] = {}
        descriptors = (
            ("name", "اسم الملف", "متطلباتي"),
            ("min_ram_gb", "الحد الأدنى RAM (GB)", "مثال: 16"),
            ("min_logical_processors", "الحد الأدنى للمعالجات المنطقية", "مثال: 8"),
            ("min_storage_gb", "الحد الأدنى لسعة التخزين (GB)", "مثال: 512"),
            ("max_price_dzd", "الميزانية القصوى (دج)", "مثال: 80000"),
            ("min_warranty_months", "الضمان الأدنى (بالأشهر)", "مثال: 12"),
            ("seller_model", "الموديل الذي صرح به البائع", "اختياري"),
            ("seller_ram_gb", "RAM المعلنة (GB)", "اختياري"),
            ("asking_price_dzd", "سعر العرض الفعلي (دج)", "إدخال من البائع"),
            ("warranty_months", "ضمان العرض الفعلي (أشهر)", "إدخال من البائع"),
        )
        for index, (key, title, placeholder) in enumerate(descriptors):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(_label(title), False, False, 0)
            entry = Gtk.Entry()
            entry.set_placeholder_text(placeholder)
            if key != "name" and key != "seller_model":
                entry.set_direction(Gtk.TextDirection.LTR)
                entry.set_alignment(1.0)
            else:
                entry.set_direction(Gtk.TextDirection.RTL)
            if key == "name":
                entry.set_text("متطلباتي")
            box.pack_start(entry, False, False, 0)
            self.fields[key] = entry
            grid.attach(box, index % 2, index // 2, 1, 1)
        self.require_ssd = Gtk.CheckButton(label="أشترط وجود SSD")
        grid.attach(self.require_ssd, 0, 5, 2, 1)
        self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.editor.pack_start(grid, False, False, 0)

        self.editor.pack_start(_label("مجالات العمل المطلوبة"), False, False, 0)
        tasks = Gtk.Grid(column_spacing=14, row_spacing=7)
        self.workloads: dict[str, Gtk.CheckButton] = {}
        for index, (ident, title, *_other) in enumerate(WORKLOADS):
            check = Gtk.CheckButton(label=title)
            self.workloads[ident] = check
            tasks.attach(check, index % 2, index // 2, 1, 1)
        self.editor.pack_start(tasks, False, False, 0)
        self.pack_start(self.editor, False, False, 0)

        self.apply_button = Gtk.Button(label="تطبيق المتطلبات")
        self.copy_button = Gtk.Button(label="نسخ ملف JSON")
        self.paste_button = Gtk.Button(label="استيراد JSON من الحافظة")
        self.save_usb_button = Gtk.Button(label="تصدير الملف إلى USB")
        self.list_usb_button = Gtk.Button(label="عرض ملفات USB")
        self.load_usb_button = Gtk.Button(label="استيراد الملف المحدد")
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_homogeneous(False)
        for button in (self.apply_button, self.copy_button, self.paste_button,
                       self.save_usb_button):
            actions.pack_start(button, False, False, 0)
        self.editor.pack_start(actions, False, False, 0)

        select_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.usb_select = Gtk.ComboBoxText()
        self.usb_select.set_hexpand(True)
        select_row.pack_start(self.list_usb_button, False, False, 0)
        select_row.pack_start(self.usb_select, True, True, 0)
        select_row.pack_start(self.load_usb_button, False, False, 0)
        self.pack_start(select_row, False, False, 0)

        self.message = _label("لم يُحفظ أو يُستورد ملف بعد.")
        self.pack_start(self.message, False, False, 0)

        self.pack_start(_label("نتيجة مقارنة المتطلبات — ليست شهادة سلامة أو تقييمًا لسعر السوق"),
                        False, False, 0)
        self.result = Gtk.TextView()
        self.result.set_editable(False)
        self.result.set_cursor_visible(False)
        self.result.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.result.set_direction(Gtk.TextDirection.RTL)
        self.result.set_justification(Gtk.Justification.LEFT)
        self.result.set_left_margin(12)
        self.result.set_right_margin(12)
        self.result.set_top_margin(10)
        self.result.set_bottom_margin(10)
        summary = Gtk.ScrolledWindow()
        summary.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        summary.set_min_content_height(220)
        summary.add(self.result)
        self.pack_start(summary, True, True, 0)

        self.apply_button.connect("clicked", self.apply)
        self.copy_button.connect("clicked", self.copy_json)
        self.paste_button.connect("clicked", self.paste_json)
        self.save_usb_button.connect("clicked", self.save_usb)
        self.list_usb_button.connect("clicked", self.list_usb)
        self.load_usb_button.connect("clicked", self.load_usb)
        self.general_mode.connect("toggled", self._on_mode_toggle)
        self.general_mode.set_active(True)
        self._on_mode_toggle()
        self._refresh()

    def _on_mode_toggle(self, *_args) -> None:
        active = self.custom_mode.get_active()
        self.editor.set_sensitive(active)
        if not active:
            self.profile = None
            self.offer = {}
            self._refresh()
            self._on_changed()

    def set_report(self, report: dict | None) -> None:
        self.report = report
        self._refresh()

    def _refresh(self) -> None:
        text = personal_text(self.report, self.profile, self.offer)
        self.result.get_buffer().set_text(_rtl_lines(text))

    def _alert(self, title: str, details: str) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self.get_toplevel(), flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK,
            text=title)
        dlg.format_secondary_text(details[:500])
        dlg.set_direction(Gtk.TextDirection.RTL)
        dlg.run()
        dlg.destroy()

    def _parse_field(self, key: str, integer: bool = False) -> float | int | None:
        raw = self.fields[key].get_text().strip()
        if not raw:
            return None
        try:
            # Integer values are intentionally strict; no hidden rounding.
            result = int(raw) if integer else float(raw)
        except (ValueError, OverflowError) as exc:
            raise ProfileError(f"قيمة غير صالحة في {key}.") from exc
        return result

    def _build(self) -> tuple[dict, dict]:
        profile = {"profile_schema_version": 1,
                   "name": self.fields["name"].get_text().strip()}
        req = {}
        for key in ("min_ram_gb", "min_logical_processors", "min_storage_gb"):
            value = self._parse_field(key, integer=key == "min_logical_processors")
            if value is not None:
                req[key] = value
        if self.require_ssd.get_active():
            req["require_ssd"] = True
        if req:
            profile["requirements"] = req
        selected = [key for key, check in self.workloads.items()
                    if check.get_active()]
        if selected:
            profile["workloads"] = selected
        for key in ("max_price_dzd", "min_warranty_months"):
            value = self._parse_field(key, integer=True)
            if value is not None:
                profile[key] = value
        claims = {}
        model = self.fields["seller_model"].get_text().strip()
        if model:
            claims["model"] = model
        ram = self._parse_field("seller_ram_gb")
        if ram is not None:
            claims["ram_gb"] = ram
        if claims:
            profile["seller_claims"] = claims
        offer = {}
        for key in ("asking_price_dzd", "warranty_months"):
            value = self._parse_field(key, integer=True)
            if value is not None:
                offer[key] = value
        return validate_profile(profile), validate_offer(offer)

    def apply(self, *_args) -> None:
        if not self.custom_mode.get_active():
            self.profile = None
            self.offer = {}
        else:
            try:
                self.profile, self.offer = self._build()
            except (ValueError, TypeError) as exc:
                self._alert("ملف غير صالح", str(exc))
                return
        self._refresh()
        self._on_changed()
        self.message.set_text("تم تطبيق المتطلبات في الذاكرة؛ لا يتغير التقرير الخام.")

    def _load_fields(self, profile: dict) -> None:
        p = validate_profile(profile)
        for entry in self.fields.values():
            entry.set_text("")
        self.fields["name"].set_text(p["name"])
        for key, value in p.get("requirements", {}).items():
            if key != "require_ssd":
                self.fields[key].set_text(str(value))
        self.require_ssd.set_active(p.get("requirements", {}).get("require_ssd", False))
        for key in ("max_price_dzd", "min_warranty_months"):
            if key in p:
                self.fields[key].set_text(str(p[key]))
        claims = p.get("seller_claims", {})
        for key, field in (("model", "seller_model"), ("ram_gb", "seller_ram_gb")):
            if key in claims:
                self.fields[field].set_text(str(claims[key]))
        for ident, check in self.workloads.items():
            check.set_active(ident in p.get("workloads", []))
        self.custom_mode.set_active(True)
        self.profile, self.offer = p, {}
        self._refresh()
        self._on_changed()

    def copy_json(self, *_args) -> None:
        try:
            profile, _offer = self._build()
            contents = dump_profile_json(profile)
        except (ValueError, TypeError) as exc:
            self._alert("ملف غير صالح", str(exc))
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(contents, -1)
        clipboard.store()
        self.message.set_text("نُسخ JSON إلى الحافظة؛ لم يُحفظ ملف دائم.")

    def paste_json(self, *_args) -> None:
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        raw = clipboard.wait_for_text()
        try:
            self._load_fields(load_profile_json(raw))
        except (ValueError, TypeError) as exc:
            self._alert("تعذّر الاستيراد", str(exc))
            return
        self.message.set_text("استُورد ملف المتطلبات من الحافظة إلى الذاكرة.")

    def _job(self, operation: str, arg: Any = None) -> None:
        if self._busy:
            return
        self._busy = True
        self.message.set_text("جارٍ التعامل مع قسم بيانات USB الموثوق...")
        for button in (self.save_usb_button, self.list_usb_button, self.load_usb_button):
            button.set_sensitive(False)

        def worker() -> None:
            try:
                if operation == "save":
                    output = save_profile_to_usb(arg)
                elif operation == "list":
                    output = list_usb_profiles()
                else:
                    output = load_profile_from_usb(arg)
                GLib.idle_add(self._job_done, operation, output, None)
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                GLib.idle_add(self._job_done, operation, None, str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def _job_done(self, operation: str, output: Any, error: str | None) -> bool:
        self._busy = False
        for button in (self.save_usb_button, self.list_usb_button, self.load_usb_button):
            button.set_sensitive(True)
        if error:
            self.message.set_text("فشل: " + error[:300])
            self._alert("تعذّر الوصول إلى USB", error)
            return False
        if operation == "save":
            self.message.set_text(
                "تم حفظ ملف المتطلبات والتحقق من SHA-256: " + str(output["filename"]))
        elif operation == "list":
            self.usb_select.remove_all()
            for item in output:
                self.usb_select.append(item["filename"], item["name"] +
                                       " — " + item["filename"])
            if output:
                self.usb_select.set_active(0)
            self.message.set_text(f"عُثر على {len(output)} ملف متطلبات على USB.")
        elif operation == "load":
            try:
                self._load_fields(output)
            except (ValueError, TypeError) as exc:
                self._alert("الملف غير صالح", str(exc))
                return False
            self.message.set_text("تم استيراد ملف المتطلبات إلى الذاكرة.")
        return False

    def save_usb(self, *_args) -> None:
        try:
            profile, _offer = self._build()
        except (ValueError, TypeError) as exc:
            self._alert("ملف غير صالح", str(exc))
            return
        self._job("save", profile)

    def list_usb(self, *_args) -> None:
        self._job("list")

    def load_usb(self, *_args) -> None:
        selected = self.usb_select.get_active_id()
        if selected is None:
            self.message.set_text("اعرض ملفات USB أولًا واختر الملف المطلوب.")
            return
        self._job("load", selected)
