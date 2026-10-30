"""Bounded, observational hardware discovery from sysfs (no disk writes).

Optional lspci gives human PCI names. Only display controller classes,
DRM connectors, and nonvirtual network adapters are included. Hardware
identifiers remain local: no MAC address, serial, EDID raw bytes, or SSID.
"""
from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

PCI_ROOT = Path("/sys/bus/pci/devices")
DRM_ROOT = Path("/sys/class/drm")
NET_ROOT = Path("/sys/class/net")
MAX_ITEMS = 32


def value(path: Path, max_chars: int = 200) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[:max_chars] or None
    except (OSError, ValueError):
        return None


def entries(path: Path, max_items: int = MAX_ITEMS) -> list[Path]:
    try:
        return sorted(path.iterdir(), key=lambda item: item.name)[:max_items]
    except (OSError, ValueError):
        return []


def pci_names() -> dict[str, str]:
    """Human-readable lspci names only; no permission or network needed."""
    try:
        output = subprocess.run(
            ["lspci", "-D", "-nn"], capture_output=True, text=True,
            timeout=2, check=False, errors="replace",
        )
        if output.returncode != 0:
            return {}
    except (OSError, subprocess.TimeoutExpired):
        return {}
    names = {}
    for line in output.stdout[:40_000].splitlines():
        match = re.match(r"^([0-9a-fA-F:.]+)\s+[^:]+:\s+(.+)$", line)
        if match:
            names[match.group(1)] = match.group(2)[:180]
    return names


def graphics_inventory(root: Path = PCI_ROOT) -> list[dict[str, Any]]:
    names = pci_names()
    items: list[dict[str, Any]] = []
    for device in entries(root, 256):
        device_class = value(device / "class")
        if not device_class or not device_class.lower().startswith("0x03"):
            continue
        vendor = value(device / "vendor")
        identifier = value(device / "device")
        if not vendor or not identifier:
            continue
        items.append({
            "bus_address": device.name,
            "class_code": device_class,
            "vendor_id": vendor,
            "device_id": identifier,
            "description": names.get(device.name),
            "source": "sysfs_pci_and_optional_lspci",
            "test_status": "not_tested",
            "note": "اكتشاف متحكم الرسوم لا يثبت قدرته أو سلامته أو أداء الألعاب.",
        })
        if len(items) >= 8:
            break
    return items


def edid_manufacture_date(blob: bytes) -> dict[str, int] | None:
    """EDID week/year denote the monitor panel, not the computer's age."""
    if len(blob) < 128 or blob[:8] != bytes.fromhex("00ffffffffffff00"):
        return None
    # EDID 1.x: week 1..53, year offset 1990; 0, 0xff are not dates.
    week, year = blob[16], 1990 + blob[17]
    if 1 <= week <= 53 and 1990 <= year <= 2100:
        return {"week": week, "year": year}
    return None


def display_inventory(root: Path = DRM_ROOT) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for connector in entries(root, 128):
        if not re.fullmatch(r"card\d+-.+", connector.name):
            continue
        status = value(connector / "status")
        if status not in ("connected", "disconnected", "unknown"):
            continue
        modes = value(connector / "modes", 3000) or ""
        try:
            raw = (connector / "edid").read_bytes()[:256] if status == "connected" else b""
        except (OSError, ValueError):
            raw = b""
        items.append({
            "connector": connector.name,
            "connection_status": status,
            "reported_modes": modes.splitlines()[:6],
            "panel_manufacture_date": edid_manufacture_date(raw),
            "source": "drm_sysfs_and_edid_if_available",
            "test_status": "not_tested",
            "note": "دقة أو تاريخ EDID لا يثبت سلامة الشاشة أو تاريخ تصنيع الحاسوب.",
        })
        if len(items) >= 12:
            break
    return items


def network_inventory(root: Path = NET_ROOT) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for interface in entries(root, 128):
        if interface.name == "lo" or not (interface / "device").exists():
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", interface.name):
            continue
        wireless = (interface / "wireless").exists() or (interface / "phy80211").exists()
        items.append({
            "interface": interface.name,
            "kind": "wifi" if wireless else "wired_or_other",
            "operational_state": value(interface / "operstate"),
            "vendor_id": value(interface / "device" / "vendor"),
            "device_id": value(interface / "device" / "device"),
            "source": "sysfs_net",
            "test_status": "not_tested",
            "note": "اكتشاف بطاقة شبكة لا يثبت الاتصال أو سرعة النقل.",
        })
        if len(items) >= 16:
            break
    return items


def collect_extensions() -> dict[str, Any]:
    return {
        "graphics": graphics_inventory(),
        "displays": display_inventory(),
        "networks": network_inventory(),
        "source": "read_only_sysfs_lspci_optional",
        "health_tested": False,
        "limitations": "الجرد لا يعني اختبار صحة GPU أو الشاشة أو الشبكة؛ عدم الكشف لا يثبت الغياب.",
    }


def age_evidence(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Supported clocks only; deliberately no claimed computer manufacture age."""
    records: list[dict[str, Any]] = []
    bios = report.get("bios")
    if isinstance(bios, dict) and bios.get("bios_date"):
        records.append({
            "component": "bios", "kind": "firmware_date",
            "value": bios["bios_date"], "source": "sysfs_dmi_bios_date",
            "limitations": "تاريخ إصدار BIOS وليس تاريخ تصنيع الحاسوب.",
        })
    for disk in report.get("storage", []) if isinstance(report.get("storage"), list) else []:
        if not isinstance(disk, dict):
            continue
        smart = disk.get("smart")
        hours = smart.get("power_on_hours") if isinstance(smart, dict) else None
        if type(hours) in (int, float) and 0 <= hours < 10**9:
            records.append({
                "component": "storage", "path": disk.get("path"), "kind": "powered_hours",
                "value": hours, "unit": "hours", "source": "smartctl_power_on_time",
                "limitations": "ساعات القرص تراكمية وليست العمر التقويمي للجهاز؛ يمكن نقل القرص أو استبداله.",
            })
    extensions = report.get("hardware_extensions")
    if isinstance(extensions, dict):
        for screen in extensions.get("displays", []) if isinstance(extensions.get("displays"), list) else []:
            if isinstance(screen, dict) and isinstance(screen.get("panel_manufacture_date"), dict):
                records.append({
                    "component": "display", "connector": screen.get("connector"),
                    "kind": "edid_panel_date", "value": screen["panel_manufacture_date"],
                    "source": "drm_edid",
                    "limitations": "تاريخ شاشة EDID غير مؤكد تصنيع الجهاز؛ قد تُستبدل الشاشة.",
                })
    return records
