"""Privileged, narrowly scoped USB report writer.

Only a partition under a kernel-reported USB disk and labeled PCINSPDATA
or Ventoy is eligible. Internal disks are NEVER candidates. No formatting.
Input: JSON report on stdin. Output: JSON save receipt on stdout.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

from .report import make_html

MOUNT_DIR = Path("/run/pc-inspector-media")
ALLOWED_LABELS = ("PCINSPDATA", "Ventoy")
ALLOWED_FS = ("vfat", "exfat")
MAX_REPORT_BYTES = 2_000_000
SAFE_PATH = re.compile(r"^/dev/[A-Za-z0-9._/-]+$")


def find_usb_partition(tree: dict) -> dict | None:
    """Select a data partition only beneath a confirmed USB transport disk."""
    found = []
    for disk in tree.get("blockdevices", []):
        if disk.get("type") != "disk" or str(disk.get("tran") or "").lower() != "usb":
            continue
        for partition in disk.get("children") or []:
            if partition.get("type") != "part":
                continue
            label = partition.get("label")
            fstype = str(partition.get("fstype") or "").lower()
            path = partition.get("path")
            if (label in ALLOWED_LABELS and fstype in ALLOWED_FS and
                    isinstance(path, str) and SAFE_PATH.fullmatch(path) and
                    ".." not in path):
                found.append(partition)
    found.sort(key=lambda d: (0 if d.get("label") == "PCINSPDATA" else 1,
                              str(d.get("path"))))
    return found[0] if found else None


def discover() -> dict | None:
    result = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,PATH,TYPE,TRAN,LABEL,FSTYPE,MOUNTPOINT"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode != 0:
        return None
    return find_usb_partition(json.loads(result.stdout))


def validated_ventoy_mapper(
    physical_partition: str,
    mapper: Path = Path("/dev/mapper/VentoyPart"),
    sys_block: Path = Path("/sys/class/block"),
) -> str | None:
    """Accept Ventoy's alias only if its sole underlying slave is our USB part.

    A mapper's name alone is NEVER proof it belongs to a removable USB.
    The physical partition must already have passed the lsblk USB+label check.
    """
    if not isinstance(physical_partition, str) or not SAFE_PATH.fullmatch(
        physical_partition
    ) or ".." in physical_partition:
        return None
    try:
        device = mapper.resolve(strict=True)
        if not re.fullmatch(r"dm-\\d+", device.name):
            return None
        if not stat.S_ISBLK(device.stat().st_mode):
            return None
        slaves = {p.name for p in (sys_block / device.name / "slaves").iterdir()}
        if slaves != {Path(physical_partition).name}:
            return None
    except (OSError, ValueError):
        return None
    return str(mapper)


def mount_usb_data(partition: dict) -> Path:
    """Mount only a validated USB data partition (or verified Ventoy alias)."""
    MOUNT_DIR.mkdir(parents=True, exist_ok=True)
    devices = [partition["path"]]
    if partition.get("label") == "Ventoy":
        alias = validated_ventoy_mapper(partition["path"])
        if alias:
            devices.append(alias)
    errors = []
    for source in devices:
        result = subprocess.run(
            ["mount", "-o", "rw,nosuid,nodev,noexec", "--", source, str(MOUNT_DIR)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if result.returncode == 0:
            return MOUNT_DIR
        # Keep useful diagnostic detail, but limit output from external tools.
        detail = (result.stderr or result.stdout or "unknown mount error").strip()
        errors.append(source + ": " + detail[:280])
    raise RuntimeError(
        "Could not mount the USB data partition read-write. "
        + "; ".join(errors)
        + ". Ventoy may keep its ISO partition busy; "
        "an independent PCINSPDATA USB drive is a safe alternative."
    )


def report_destination() -> Path:
    partition = discover()
    if not partition:
        raise RuntimeError(
            "No writable USB data partition labeled PCINSPDATA or Ventoy was found."
        )
    mounted = partition.get("mountpoint")
    if mounted:
        target = Path(mounted)
        if not target.is_dir():
            raise RuntimeError("Reported USB mount point is not a directory.")
        if os.statvfs(target).f_flag & os.ST_RDONLY:
            raise RuntimeError(
                "USB data partition is mounted read-only; cannot save report."
            )
    else:
        target = mount_usb_data(partition)
    if not os.access(target, os.W_OK):
        raise RuntimeError("USB data partition is not writable.")
    reports = target / "PC-Inspector-Reports"
    reports.mkdir(mode=0o755, exist_ok=True)
    return reports


def validate(report: object) -> dict:
    if not isinstance(report, dict):
        raise ValueError("Report must be an object.")
    if report.get("schema_version") != 1:
        raise ValueError("Unsupported report schema.")
    if not isinstance(report.get("storage"), list):
        raise ValueError("Invalid report storage data.")
    if not isinstance(report.get("bios"), dict):
        raise ValueError("Invalid BIOS data.")
    if not isinstance(report.get("findings"), list):
        raise ValueError("Invalid findings.")
    return report


def save(report: dict) -> dict:
    report = validate(report)
    folder = report_destination()
    basename = "pc-inspector-" + dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    json_file = folder / (basename + ".json")
    html_file = folder / (basename + ".html")
    # 'x' refuses clobbering existing reports; never touches internal disks.
    with json_file.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    with html_file.open("x", encoding="utf-8") as handle:
        handle.write(make_html(report))
        handle.flush()
        os.fsync(handle.fileno())
    return {"saved": True, "json": str(json_file), "html": str(html_file)}


def main() -> int:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print(json.dumps({"saved": False, "error": "root_required"}))
        return 1
    raw = sys.stdin.buffer.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        print(json.dumps({"saved": False, "error": "report_too_large"}))
        return 1
    try:
        report = validate(json.loads(raw.decode("utf-8")))
        receipt = save(report)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        receipt = {"saved": False, "error": str(exc)}
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["saved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
