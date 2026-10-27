"""Verified report bundles, confined to a previously authenticated USB mount.

Creates a unique session directory without clobbering prior scans. A completion
manifest is the last published file. No writes occur outside the supplied mount.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

REPORTS_DIR = "PC-Inspector-Reports"
SESSION_PATTERN = re.compile(r"pc-inspector-\d{8}T\d{6}Z-[0-9a-f]{8,32}\Z")
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_BUNDLE_BYTES = 8_000_000
FREE_SPACE_RESERVE = 256 * 1024


def _open_directory(name: str, parent_fd: int | None = None) -> int:
    kwargs = {"dir_fd": parent_fd} if parent_fd is not None else {}
    fd = os.open(name, DIR_FLAGS, **kwargs)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise RuntimeError("Report directory is not a directory.")
    return fd


def _write_verified(dir_fd: int, filename: str, payload: bytes) -> str:
    """Durably write a file, read it back, then atomically reveal its final name."""
    temp_name = "." + filename + ".partial"
    handle = os.open(temp_name, FILE_FLAGS, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        with os.fdopen(
            os.open(temp_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd),
            "rb",
        ) as stream:
            stored = stream.read(len(payload) + 1)
        if stored != payload:
            raise RuntimeError("USB verification failed: written content differs.")
        digest = hashlib.sha256(payload).hexdigest()
        # This private, newly-created session directory contains no final names.
        os.rename(temp_name, filename, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        os.fsync(dir_fd)
        return digest
    finally:
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except FileNotFoundError:
            pass


def store_verified_bundle(
    usb_mount: Path, session: str, json_bytes: bytes, html_bytes: bytes,
) -> dict[str, object]:
    """Save JSON+HTML and completion marker; previous sessions are immutable.

    The caller MUST authenticate usb_mount as an external USB data filesystem.
    An interrupted session remains incomplete, and is never acknowledged as saved.
    """
    if not SESSION_PATTERN.fullmatch(session):
        raise ValueError("Invalid report session name.")
    if not isinstance(json_bytes, bytes) or not isinstance(html_bytes, bytes):
        raise TypeError("Report contents must be byte strings.")
    if len(json_bytes) + len(html_bytes) > MAX_BUNDLE_BYTES:
        raise ValueError("Report bundle too large.")
    available = os.statvfs(usb_mount)
    free_bytes = available.f_bavail * available.f_frsize
    if free_bytes < len(json_bytes) + len(html_bytes) + FREE_SPACE_RESERVE:
        raise RuntimeError("Insufficient free space on USB report partition.")

    rootfd = _open_directory(str(usb_mount))
    try:
        try:
            os.mkdir(REPORTS_DIR, 0o700, dir_fd=rootfd)
        except FileExistsError:
            pass
        reports_fd = _open_directory(REPORTS_DIR, rootfd)
        try:
            os.mkdir(session, 0o700, dir_fd=reports_fd)
            session_fd = _open_directory(session, reports_fd)
            try:
                json_digest = _write_verified(session_fd, "report.json", json_bytes)
                html_digest = _write_verified(session_fd, "report.html", html_bytes)
                manifest_bytes = (
                    json.dumps({
                        "complete": True,
                        "files": {
                            "report.json": {"sha256": json_digest,
                                            "bytes": len(json_bytes)},
                            "report.html": {"sha256": html_digest,
                                            "bytes": len(html_bytes)},
                        },
                    }, ensure_ascii=False, sort_keys=True) + "\n"
                ).encode("utf-8")
                _write_verified(session_fd, "complete.json", manifest_bytes)
                os.fsync(session_fd)
            finally:
                os.close(session_fd)
            os.fsync(reports_fd)
        finally:
            os.close(reports_fd)
        os.fsync(rootfd)
    finally:
        os.close(rootfd)

    location = usb_mount / REPORTS_DIR / session
    return {
        "saved": True,
        "json": str(location / "report.json"),
        "html": str(location / "report.html"),
        "manifest": str(location / "complete.json"),
        "json_sha256": json_digest,
        "html_sha256": html_digest,
        "verification": "readback_sha256_and_fsync",
    }
