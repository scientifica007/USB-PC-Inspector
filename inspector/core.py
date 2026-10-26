"""Offline hardware inventory. Never mounts or writes to internal disks.

Run: python3 -m inspector.core
Only allowlisted, observational commands are executed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from . import __version__

COMMAND_TIMEOUT = 12
MAX_OUTPUT = 900_000
SAFE_DEVICE = re.compile(r"^/dev/[A-Za-z0-9._/-]+$")


def run_command(argv: list[str], timeout: int = COMMAND_TIMEOUT) -> dict[str, Any]:
    """Run a predefined command without shell evaluation, bounded in time and output."""
    if not argv or shutil.which(argv[0]) is None:
        return {"ok": False, "error": "tool_unavailable"}
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            errors="replace", check=False, env={**os.environ, "LC_ALL": "C"},
        )
        return {
            "ok": result.returncode == 0, "code": result.returncode,
            "stdout": result.stdout[:MAX_OUTPUT],
            "error": result.stderr[:1500],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()[:300]
    except (OSError, ValueError):
        return None


def parse_json_command(argv: list[str]) -> tuple[dict[str, Any] | None, str | None]:
    result = run_command(argv)
    try:
        parsed = json.loads(result.get("stdout") or "")
        if isinstance(parsed, dict):
            # SMART tools can return partial valid JSON with nonzero exit codes.
            return parsed, None if result["ok"] else "nonzero_exit"
    except (ValueError, TypeError):
        pass
    return None, result.get("error") or "unreadable_response"


def bios_inventory() -> dict[str, Any]:
    root = "/sys/class/dmi/id/"
    fields = {
        "manufacturer": "sys_vendor",
        "model": "product_name",
        "board": "board_name",
        "bios_vendor": "bios_vendor",
        "bios_version": "bios_version",
        "bios_date": "bios_date",
    }
    bios = {key: read_text(root + value) for key, value in fields.items()}
    bios["boot_mode"] = "UEFI" if Path("/sys/firmware/efi").exists() else "Legacy/unknown"
    bios["secure_boot"] = "unknown"
    efivars = Path("/sys/firmware/efi/efivars")
    try:
        for name in efivars.glob("SecureBoot-*"):
            content = name.read_bytes()
            if len(content) >= 5:
                bios["secure_boot"] = "enabled" if content[4] == 1 else "disabled"
            break
    except OSError:
        pass
    return bios


def cpu_inventory() -> dict[str, Any]:
    cpuinfo = read_text("/proc/cpuinfo") or ""
    # /proc/cpuinfo is much larger than ordinary sysfs values.
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace")[:400_000]
    except OSError:
        pass
    def value(key: str) -> str | None:
        match = re.search(r"(?m)^" + re.escape(key) + r"\s*:\s*(.+)$", cpuinfo)
        return match.group(1).strip() if match else None
    return {
        "model": value("model name") or value("Hardware") or value("Processor"),
        "logical_processors": os.cpu_count(),
        "vendor": value("vendor_id"),
        "architecture": os.uname().machine,
    }


def memory_inventory() -> dict[str, Any]:
    meminfo = read_text("/proc/meminfo") or ""
    match = re.search(r"MemTotal:\s*(\d+)\s*kB", meminfo)
    total_bytes = int(match.group(1)) * 1024 if match else None
    slots: list[dict[str, str | None]] = []
    result = run_command(["dmidecode", "--type", "17"])
    if result["ok"]:
        for block in re.split(r"(?m)^Handle ", result["stdout"]):
            if "\nMemory Device\n" not in block:
                continue
            def item(k: str) -> str | None:
                found = re.search(r"(?m)^\s+" + re.escape(k) + r":\s*(.+)$", block)
                return found.group(1).strip() if found else None
            size = item("Size")
            if size and size not in ("No Module Installed", "Not Installed"):
                slots.append({
                    "locator": item("Locator"), "size": size,
                    "type": item("Type"), "speed": item("Configured Memory Speed") or item("Speed"),
                })
    return {"total_bytes": total_bytes, "slots": slots,
            "slots_status": "reported" if result["ok"] else "unavailable"}


def battery_inventory() -> list[dict[str, Any]]:
    results = []
    for base in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        def number(name: str) -> int | None:
            try:
                value = read_text(str(base / name))
                return int(value) if value is not None else None
            except ValueError:
                return None
        full = number("energy_full") or number("charge_full")
        design = number("energy_full_design") or number("charge_full_design")
        health = round(100 * full / design, 1) if full and design and design > 0 else None
        results.append({
            "name": base.name, "manufacturer": read_text(str(base / "manufacturer")),
            "model": read_text(str(base / "model_name")),
            "state": read_text(str(base / "status")),
            "estimated_health_percent": health,
            "health_source": "battery_firmware_reported" if health is not None else "unavailable",
        })
    return results


def list_internal_disks() -> tuple[list[dict[str, Any]], str | None]:
    data, error = parse_json_command([
        "lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,TRAN,SIZE,MODEL,ROTA,RM"
    ])
    if data is None or not isinstance(data.get("blockdevices"), list):
        return [], error or "lsblk_unavailable"
    disks = []
    for device in data["blockdevices"]:
        if device.get("type") != "disk":
            continue
        # Never inspect the USB boot drive, including USB-attached SSDs.
        if str(device.get("tran") or "").lower() == "usb":
            continue
        path = device.get("path")
        if not isinstance(path, str) or not SAFE_DEVICE.fullmatch(path) or ".." in path:
            continue
        disks.append({
            "path": path,
            "model": device.get("model"),
            "size_bytes": device.get("size"),
            "transport": device.get("tran"),
            "rotational": device.get("rota"),
            "removable": device.get("rm"),
        })
    return disks, error


def smart_summary(device: str) -> dict[str, Any]:
    if not SAFE_DEVICE.fullmatch(device) or ".." in device:
        return {"status": "not_tested", "reason": "invalid_device"}
    data, error = parse_json_command(["smartctl", "-a", "-j", device])
    if data is None:
        return {"status": "unavailable", "reason": error}
    smart = data.get("smart_status") or {}
    on_time = data.get("power_on_time") or {}
    temp = data.get("temperature") or {}
    nvme = data.get("nvme_smart_health_information_log") or {}
    ata = data.get("ata_smart_data") or {}
    return {
        "status": "reported" if not error else "partial",
        "read_warning": error,
        "overall_passed": smart.get("passed"),
        "power_on_hours": on_time.get("hours"),
        "temperature_c": temp.get("current"),
        "nvme_percentage_used": nvme.get("percentage_used"),
        "nvme_media_errors": nvme.get("media_errors"),
        "nvme_critical_warning": nvme.get("critical_warning"),
        "ata_selftest_status": (ata.get("self_test") or {}).get("status"),
        "note": "Device-reported data; not proof of age, newness, or absence of faults.",
    }


def build_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if report["disk_probe_error"]:
        findings.append({"level": "unknown", "code": "disk_scan_unavailable",
                         "message": "تعذر حصر الأقراص؛ لا يمكن الحكم على وجود قرص داخلي."})
    elif not report["storage"]:
        findings.append({"level": "info", "code": "no_internal_disk_detected",
                         "message": "لم يُكتشف قرص داخلي. يمكن للنظام العمل دون قرص، لكن قد تكون هناك مشكلة في التعرف على وحدة التخزين."})
    for disk in report["storage"]:
        smart = disk["smart"]
        if smart["status"] in ("unavailable", "not_tested"):
            findings.append({"level": "unknown", "code": "smart_unavailable",
                             "message": "بيانات صحة القرص غير متاحة: " + str(disk["path"])})
        if smart.get("overall_passed") is False:
            findings.append({"level": "warning", "code": "smart_failed",
                             "message": "القرص أبلغ عن إخفاق في تقييم SMART: " + str(disk["path"])})
        if isinstance(smart.get("power_on_hours"), (int, float)) and smart["power_on_hours"] > 1000:
            findings.append({"level": "info", "code": "drive_hours",
                             "message": "ساعات تشغيل مسجلة للقرص تتجاوز 1000 ساعة؛ لا تثبت بمفردها عمر الحاسوب."})
        if isinstance(smart.get("nvme_percentage_used"), (int, float)) and smart["nvme_percentage_used"] >= 80:
            findings.append({"level": "warning", "code": "nvme_wear",
                             "message": "مؤشر تآكل NVMe المعلن مرتفع؛ تحقق من سياق الجهاز."})
    for batt in report["battery"]:
        health = batt.get("estimated_health_percent")
        if isinstance(health, (int, float)) and health < 70:
            findings.append({"level": "warning", "code": "battery_wear",
                             "message": "السعة الحالية التي تبلغ عنها البطارية أقل من 70% من السعة التصميمية."})
    if not findings:
        findings.append({"level": "info", "code": "limited_scan",
                         "message": "لم تظهر إنذارات وفق البيانات المتاحة؛ لا يُعد ذلك شهادة بسلامة الحاسوب."})
    return findings


def collect() -> dict[str, Any]:
    disks, disk_error = list_internal_disks()
    for disk in disks:
        disk["smart"] = smart_summary(disk["path"])
    report = {
        "schema_version": 1,
        "tool_version": __version__,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "observational_only",
        "scope": "internal disks only; USB boot media excluded",
        "bios": bios_inventory(),
        "cpu": cpu_inventory(),
        "memory": memory_inventory(),
        "battery": battery_inventory(),
        "storage": disks,
        "disk_probe_error": disk_error,
        "tool_availability": {
            tool: shutil.which(tool) is not None
            for tool in ("lsblk", "smartctl", "dmidecode")
        },
        "disclaimer": "Only a preliminary inventory. No stress test, complete RAM test, malware check, or BIOS integrity proof was performed.",
    }
    report["findings"] = build_findings(report)
    return report


def main() -> None:
    print(json.dumps(collect(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
