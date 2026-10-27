"""Read-only SMART interpretation. smartctl exit status is a bitmask, not a pass/fail flag."""
from __future__ import annotations

from typing import Any

EXIT_FLAGS = {
    0: "command_line_error",
    1: "device_open_or_identify_failed",
    2: "smart_command_or_checksum_failed",
    3: "smart_status_failing",
    4: "prefail_attribute_at_or_below_threshold",
    5: "attribute_failed_in_the_past",
    6: "error_log_contains_records",
    7: "self_test_log_contains_records",
}
CRITICAL_BITS = (3, 4)
HISTORICAL_BITS = (5, 6, 7)
READ_FAILURE_BITS = (0, 1, 2)


def decode_exit(code: Any) -> dict[str, Any]:
    """Decode only documented nonnegative 8-bit smartctl exit codes."""
    if type(code) is not int or not 0 <= code <= 255:
        return {"known": False, "code": code, "flags": [], "critical": None,
                "historical": None, "read_failure": None}
    flags = [name for bit, name in EXIT_FLAGS.items() if code & (1 << bit)]
    return {"known": True, "code": code, "flags": flags,
            "critical": any(code & (1 << bit) for bit in CRITICAL_BITS),
            "historical": any(code & (1 << bit) for bit in HISTORICAL_BITS),
            "read_failure": any(code & (1 << bit) for bit in READ_FAILURE_BITS)}


def interpret(data: dict[str, Any], code: Any, stderr: str | None = None) -> dict[str, Any]:
    """Keep relevant evidence without serial numbers or unbounded raw command output."""
    exit_info = decode_exit(code)
    smart = data.get("smart_status")
    on_time = data.get("power_on_time")
    temp = data.get("temperature")
    nvme = data.get("nvme_smart_health_information_log")
    ata = data.get("ata_smart_data")
    smart = smart if isinstance(smart, dict) else {}
    on_time = on_time if isinstance(on_time, dict) else {}
    temp = temp if isinstance(temp, dict) else {}
    nvme = nvme if isinstance(nvme, dict) else {}
    ata = ata if isinstance(ata, dict) else {}
    self_test = ata.get("self_test")
    self_test = self_test if isinstance(self_test, dict) else {}
    evidence = {
        "smart_status": smart,
        "power_on_time": on_time,
        "temperature": temp,
        "nvme_smart_health_information_log": nvme,
        "ata_self_test": self_test,
        "ata_smart_attributes": data.get("ata_smart_attributes"),
        "ata_smart_error_log": data.get("ata_smart_error_log"),
        "ata_smart_self_test_log": data.get("ata_smart_self_test_log"),
    }
    # Restrict evidence to selected diagnostic fields; full raw JSON may include
    # serial numbers, WWNs, and other device identifiers.
    evidence = {k: v for k, v in evidence.items() if v is not None}
    return {
        "status": "reported" if code == 0 else "partial",
        "read_warning": None if code == 0 else "nonzero_exit",
        "smartctl_exit": exit_info,
        "overall_passed": smart.get("passed"),
        "power_on_hours": on_time.get("hours"),
        "temperature_c": temp.get("current"),
        "nvme_percentage_used": nvme.get("percentage_used"),
        "nvme_media_errors": nvme.get("media_errors"),
        "nvme_critical_warning": nvme.get("critical_warning"),
        "ata_selftest_status": self_test.get("status"),
        "diagnostic_evidence": evidence,
        "evidence_scope": "selected_smartctl_json_fields_not_full_raw_output",
        "note": "Historical SMART log entries are not proof of current failure. A passing SMART status does not certify a healthy drive.",
    }
