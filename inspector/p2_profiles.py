"""P2 buyer profiles: optional, offline, evidence-qualified rules.

This module does not collect data, probe hardware, change L1 health/purchase
verdicts, run benchmarks, or write files. Only explicit callers import/export
profiles; an absent profile leaves the generic experience unchanged.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .p1_evaluation import WORKLOADS, installed_ram_gb

PROFILE_SCHEMA_VERSION = 1
MAX_PROFILE_BYTES = 65536
WORKLOAD_IDS = frozenset(entry[0] for entry in WORKLOADS)
PROFILE_KEYS = frozenset(("profile_schema_version", "name", "workloads",
                          "requirements", "max_price_dzd", "min_warranty_months",
                          "seller_claims"))
REQUIREMENT_KEYS = frozenset(("min_ram_gb", "min_logical_processors",
                              "min_storage_gb", "require_ssd"))
SELLER_KEYS = frozenset(("model", "ram_gb"))
OFFER_KEYS = frozenset(("asking_price_dzd", "warranty_months"))


class ProfileError(ValueError):
    """Unsupported or malformed profile; never silently drop requested rules."""


def _object(value: Any, keys: frozenset[str], label: str) -> dict:
    if not isinstance(value, dict) or any(type(k) is not str for k in value):
        raise ProfileError(f"{label}: expected JSON object")
    unknown = set(value) - keys
    if unknown:
        raise ProfileError(f"{label}: unsupported fields {', '.join(sorted(unknown))}")
    return value


def _number(value: Any, name: str, maximum: int, *, integer: bool = False) -> None:
    if integer:
        if type(value) is not int:
            raise ProfileError(f"{name}: integer required")
    elif type(value) not in (int, float):
        raise ProfileError(f"{name}: number required")
    try:
        valid = 0 <= value <= maximum and (type(value) is int or math.isfinite(value))
    except (TypeError, OverflowError):
        valid = False
    if not valid:
        raise ProfileError(f"{name}: out of range or nonfinite")


def _text(value: Any, label: str, limit: int) -> None:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > limit or any(ord(c) < 32 for c in value)):
        raise ProfileError(f"{label}: nonblank bounded text required")


def validate_profile(value: Any) -> dict:
    """Validate v1 and return a detached JSON structure, not the supplied object."""
    p = _object(value, PROFILE_KEYS, "profile")
    if type(p.get("profile_schema_version")) is not int or p["profile_schema_version"] != 1:
        raise ProfileError("unsupported profile_schema_version")
    _text(p.get("name"), "name", 80)
    if "workloads" in p:
        tasks = p["workloads"]
        if (not isinstance(tasks, list) or len(tasks) > len(WORKLOAD_IDS)
                or any(type(t) is not str or t not in WORKLOAD_IDS for t in tasks)
                or len(set(tasks)) != len(tasks)):
            raise ProfileError("workloads: unknown/duplicate ID or invalid list")
    if "requirements" in p:
        req = _object(p["requirements"], REQUIREMENT_KEYS, "requirements")
        for field, maximum in (("min_ram_gb", 1024), ("min_storage_gb", 16384)):
            if field in req:
                _number(req[field], field, maximum)
        if "min_logical_processors" in req:
            _number(req["min_logical_processors"], "min_logical_processors", 1024,
                    integer=True)
            if req["min_logical_processors"] < 1:
                raise ProfileError("min_logical_processors must be positive")
        if "require_ssd" in req and type(req["require_ssd"]) is not bool:
            raise ProfileError("require_ssd: boolean required")
    for field, maximum in (("max_price_dzd", 1_000_000_000),
                           ("min_warranty_months", 120)):
        if field in p:
            _number(p[field], field, maximum, integer=True)
    if "seller_claims" in p:
        claims = _object(p["seller_claims"], SELLER_KEYS, "seller_claims")
        if "model" in claims:
            _text(claims["model"], "seller_claims.model", 160)
        if "ram_gb" in claims:
            _number(claims["ram_gb"], "seller_claims.ram_gb", 1024)
    try:
        return json.loads(json.dumps(p, ensure_ascii=False, allow_nan=False))
    except (ValueError, TypeError) as exc:
        raise ProfileError("profile must contain only JSON values") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    data = {}
    for k, v in pairs:
        if k in data:
            raise ProfileError(f"duplicate key: {k}")
        data[k] = v
    return data


def _reject_constant(value: str) -> None:
    raise ProfileError(f"invalid JSON constant: {value}")


def load_profile_json(payload: bytes | str) -> dict:
    """Read explicit import content in memory; reject duplicates, NaN, oversized files."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_PROFILE_BYTES:
            raise ProfileError("profile too large")
        try:
            payload = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProfileError("profile must use UTF-8") from exc
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ProfileError("profile too large or unsupported type")
    try:
        parsed = json.loads(payload, object_pairs_hook=_reject_duplicate_keys,
                            parse_constant=_reject_constant)
    except (ValueError, TypeError) as exc:
        raise ProfileError(f"invalid profile JSON: {exc}") from exc
    return validate_profile(parsed)


def dump_profile_json(profile: dict) -> str:
    return json.dumps(validate_profile(profile), ensure_ascii=False,
                      allow_nan=False, indent=2, sort_keys=True) + "\n"


def validate_offer(value: Any) -> dict:
    """Seller claims and prices are inputs, never facts measured by the scanner."""
    offer = _object(value, OFFER_KEYS, "offer")
    for key, high in (("asking_price_dzd", 1_000_000_000),
                      ("warranty_months", 120)):
        if key in offer:
            _number(offer[key], key, high, integer=True)
    return dict(offer)


def _check(key: str, status: str, reason: str) -> dict:
    return {"code": key, "status": status, "reason": reason}


def _axis(checks: list[dict]) -> dict:
    states = {c["status"] for c in checks}
    status = ("fail" if "fail" in states else
              "needs_verification" if "needs_verification" in states else
              "conditional" if "conditional" in states else
              "pass" if states else "not_assessed")
    return {"status": status, "checks": checks}


def evaluate_purchase_profile(report: dict, profile: dict | None = None,
                              offer: dict | None = None) -> dict:
    """Independent personalized verdict without mutating report or its generic verdict."""
    if not isinstance(report, dict):
        raise TypeError("report must be a dict")
    original = report.get("purchase_assessment")
    generic_verdict = (original.get("verdict", "undetermined")
                       if isinstance(original, dict) else "undetermined")
    if profile is None:
        return {"rule_version": "p2-profile-v1", "mode": "general",
                "generic_verdict": generic_verdict,
                "personal_verdict": "not_applied", "axes": {}}

    p = validate_profile(profile)
    offer = validate_offer({} if offer is None else offer)
    health = report.get("health_assessment")
    health = health if isinstance(health, dict) else {}
    if generic_verdict == "do_not_buy" or health.get("overall") == "critical":
        safety = [_check("confirmed_risk", "fail",
                         "فشل صحي مثبت أو قرار عام بعدم الشراء؛ لا يمكن لملف المتطلبات تجاوزه.")]
    else:
        safety = [_check("limited_evidence", "needs_verification",
                         "الفحص L1 لا يثبت سلامة كل المكونات.")]
    axes = {"technical_safety": _axis(safety)}
    req = p.get("requirements", {})
    checks = []
    ram_gb = installed_ram_gb(report.get("memory"))
    if "min_ram_gb" in req:
        checks.append(_check("min_ram_gb",
                             "needs_verification" if ram_gb is None else
                             "pass" if ram_gb >= req["min_ram_gb"] else "fail",
                             "سعة RAM المركبة من DMI لا MemTotal."))
    cpu = report.get("cpu")
    logical = cpu.get("logical_processors") if isinstance(cpu, dict) else None
    logical = logical if type(logical) is int and 0 < logical <= 1024 else None
    if "min_logical_processors" in req:
        checks.append(_check("min_logical_processors",
                             "needs_verification" if logical is None else
                             "pass" if logical >= req["min_logical_processors"] else "fail",
                             "عدد الأنوية المنطقية ليس معيار أداء شاملًا."))
    raw_disks = report.get("storage")
    disks = [d for d in raw_disks if isinstance(d, dict)] if isinstance(raw_disks, list) else []
    reliable = bool(disks) and not report.get("disk_probe_error")
    if "min_storage_gb" in req:
        sizes = [d.get("size_bytes") for d in disks]
        known = reliable and all(type(s) is int and 0 <= s <= 10**18 for s in sizes)
        total = sum(sizes) / 1e9 if known else None
        checks.append(_check("min_storage_gb",
                             "needs_verification" if total is None else
                             "pass" if total >= req["min_storage_gb"] else "fail",
                             "السعة الاسمية لا تثبت سلامة التخزين."))
    if req.get("require_ssd") is True:
        has_ssd = any(d.get("rotational") is False for d in disks)
        known = reliable and all(type(d.get("rotational")) is bool for d in disks)
        checks.append(_check("require_ssd",
                             "pass" if has_ssd else "fail" if known else "needs_verification",
                             "نوع التخزين المكتشف لا يثبت صحته."))
    axes["hardware_requirements"] = _axis(checks)

    suitability = report.get("suitability_assessment")
    raw_workloads = suitability.get("workloads") if isinstance(suitability, dict) else []
    work_by_id = {w["id"]: w for w in raw_workloads
                  if isinstance(w, dict) and isinstance(w.get("id"), str)} if isinstance(raw_workloads, list) else {}
    wchecks = []
    for ident in p.get("workloads", []):
        verdict = work_by_id.get(ident, {}).get("verdict")
        status = {"unsuitable": "fail", "conditional": "conditional",
                  "undetermined": "needs_verification",
                  "suitable": "conditional"}.get(verdict, "needs_verification")
        wchecks.append(_check(ident, status, "ملاءمة إرشادية، لا Benchmark أو FPS مقاس."))
    axes["workload_fit"] = _axis(wchecks)

    claims = p.get("seller_claims", {})
    cchecks = []
    if "model" in claims:
        bios = report.get("bios")
        observed = bios.get("model") if isinstance(bios, dict) else None
        status = ("needs_verification" if not isinstance(observed, str) or not observed.strip()
                  else "pass" if observed.strip().casefold() == claims["model"].strip().casefold()
                  else "fail")
        cchecks.append(_check("seller_model", status, "مقارنة وصف البائع بهوية DMI."))
    if "ram_gb" in claims:
        cchecks.append(_check("seller_ram_gb",
                              "needs_verification" if ram_gb is None else
                              "pass" if ram_gb == claims["ram_gb"] else "fail",
                              "مقارنة RAM المعلنة بالذاكرة المركبة."))
    axes["seller_claims"] = _axis(cchecks)

    economic = []
    if "max_price_dzd" in p:
        price = offer.get("asking_price_dzd")
        economic.append(_check("budget",
                               "needs_verification" if price is None else
                               "pass" if price <= p["max_price_dzd"] else "fail",
                               "السقف الشخصي بالدينار، وليس تقييمًا لسعر السوق."))
    if "min_warranty_months" in p:
        warranty = offer.get("warranty_months")
        economic.append(_check("warranty",
                               "needs_verification" if warranty is None else
                               "pass" if warranty >= p["min_warranty_months"] else "fail",
                               "مدة ضمان صرح بها البائع ولم تتحقق شروطها."))
    axes["economics"] = _axis(economic)

    states = {axis["status"] for axis in axes.values()}
    personalized = ("reject" if "fail" in states else
                    "inspect_before_payment" if states & {"needs_verification", "conditional"}
                    else "candidate_with_checks")
    return {"rule_version": "p2-profile-v1", "mode": "custom",
            "profile_name": p["name"], "generic_verdict": generic_verdict,
            "personal_verdict": personalized, "axes": axes,
            "limitations": "لا يغير ملف المتطلبات أدلة SMART أو حكم الشراء العام؛ لا يُقيم سعر السوق."}
