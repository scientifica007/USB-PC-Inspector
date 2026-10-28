"""Read-only, offline verification of USB-PC-Inspector report sessions.

QA utility for use *after* rebooting into the host OS, not a Live USB
requirement. Does not mount, format, modify, repair, or write to any device.
Prints session directory names and validation statuses, never report contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REPORTS_DIR = "PC-Inspector-Reports"
SESSION_PATTERN = re.compile(r"pc-inspector-\d{8}T\d{6}Z-[0-9a-f]{8,32}\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_REPORT_BYTES = 8_000_000
MAX_MANIFEST_BYTES = 64_000
FILES = ("report.json", "report.html")


def _read_regular(directory_fd: int, filename: str, maximum: int) -> bytes:
    """Read only a regular file without following its final symlink."""
    fd = os.open(filename, READ_FLAGS, dir_fd=directory_fd)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode):
            raise ValueError("not a regular file: " + filename)
        if meta.st_size > maximum:
            raise ValueError("file too large: " + filename)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError("file too large: " + filename)
        return payload
    finally:
        os.close(fd)


def _check_session(reports_fd: int, name: str) -> dict:
    result = {"session": name, "ok": False, "errors": []}
    errors = result["errors"]
    if SESSION_PATTERN.fullmatch(name) is None:
        errors.append("invalid session directory name")
        return result
    try:
        session_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=reports_fd)
    except (OSError, ValueError) as exc:
        errors.append("session directory unavailable or unsafe: " + type(exc).__name__)
        return result

    try:
        try:
            manifest_data = _read_regular(session_fd, "complete.json", MAX_MANIFEST_BYTES)
            manifest = json.loads(manifest_data.decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append("missing, unsafe or invalid complete.json: " + type(exc).__name__)
            return result
        if not isinstance(manifest, dict) or manifest.get("complete") is not True:
            errors.append("completion marker is not true")
            return result
        entries = manifest.get("files")
        if not isinstance(entries, dict) or set(entries) != set(FILES):
            errors.append("completion manifest file list is invalid")
            return result

        for name_on_disk in FILES:
            expected = entries[name_on_disk]
            if not isinstance(expected, dict):
                errors.append("invalid manifest entry: " + name_on_disk)
                continue
            size = expected.get("bytes")
            digest = expected.get("sha256")
            if (type(size) is not int or size < 0 or size > MAX_REPORT_BYTES
                    or not isinstance(digest, str) or
                    SHA256_PATTERN.fullmatch(digest) is None):
                errors.append("invalid manifest metadata: " + name_on_disk)
                continue
            try:
                payload = _read_regular(session_fd, name_on_disk, MAX_REPORT_BYTES)
                payload.decode("utf-8")  # JSON and HTML must be UTF-8.
            except (OSError, UnicodeError, ValueError) as exc:
                errors.append("unreadable or unsafe " + name_on_disk + ": " + type(exc).__name__)
                continue
            if len(payload) != size:
                errors.append("size mismatch: " + name_on_disk)
            if hashlib.sha256(payload).hexdigest() != digest:
                errors.append("SHA-256 mismatch: " + name_on_disk)
            if name_on_disk == "report.json":
                try:
                    report = json.loads(payload)
                    if not isinstance(report, dict) or report.get("schema_version") != 1:
                        errors.append("unsupported or invalid report.json schema")
                    else:
                        result["version"] = str(report.get("tool_version") or "unknown")
                except ValueError:
                    errors.append("report.json is not valid JSON")
    finally:
        os.close(session_fd)
    result["ok"] = not errors
    return result


def verify_partition(
    partition_root: Path, *, min_sessions: int = 1,
    required_sessions: tuple[str, ...] = (),
) -> dict:
    """Check report bundles on an already-mounted directory, without writing.

    Never creates or changes a directory, never mounts a block device. The
    caller chooses the directory; use the external PCINSPDATA USB partition.
    """
    summary = {"ok": False, "checked": 0, "sessions": [], "errors": []}
    if min_sessions < 1:
        summary["errors"].append("min_sessions must be >= 1")
        return summary
    try:
        root_fd = os.open(os.fspath(partition_root), DIRECTORY_FLAGS)
    except (OSError, ValueError) as exc:
        summary["errors"].append("partition directory unavailable or unsafe: "
                                 + type(exc).__name__)
        return summary
    try:
        try:
            reports_fd = os.open(REPORTS_DIR, DIRECTORY_FLAGS, dir_fd=root_fd)
        except (OSError, ValueError) as exc:
            summary["errors"].append("report directory unavailable or unsafe: "
                                     + type(exc).__name__)
            return summary
        try:
            candidates = sorted(
                name for name in os.listdir(reports_fd)
                if name.startswith("pc-inspector-")
            )
            for name in candidates:
                summary["sessions"].append(_check_session(reports_fd, name))
            summary["checked"] = len(candidates)
            if len(candidates) < min_sessions:
                summary["errors"].append(
                    "expected at least " + str(min_sessions) + " sessions"
                )
            for required in required_sessions:
                if required not in candidates:
                    summary["errors"].append("missing preserved session: " + required)
            if any(not session["ok"] for session in summary["sessions"]):
                summary["errors"].append("one or more report sessions failed verification")
        finally:
            os.close(reports_fd)
    finally:
        os.close(root_fd)
    summary["ok"] = not summary["errors"]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify existing USB PC Inspector reports, strictly read-only."
    )
    parser.add_argument("partition", type=Path,
                        help="already-mounted PCINSPDATA directory")
    parser.add_argument("--min-sessions", type=int, default=1)
    parser.add_argument("--require-session", action="append", default=[],
                        help="existing session directory that must still be present")
    parser.add_argument("--json", action="store_true",
                        help="show machine-readable validation results")
    options = parser.parse_args(argv)
    result = verify_partition(
        options.partition, min_sessions=options.min_sessions,
        required_sessions=tuple(options.require_session),
    )
    if options.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for entry in result["sessions"]:
            state = "PASS" if entry["ok"] else "FAIL"
            print(state + "  " + entry["session"] + " (" +
                  str(entry.get("version", "unknown")) + ")")
            for issue in entry["errors"]:
                print("  - " + issue)
        for issue in result["errors"]:
            print("FAIL  " + issue)
        print(("PASS" if result["ok"] else "FAIL") +
              ": sessions checked = " + str(result["checked"]))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
