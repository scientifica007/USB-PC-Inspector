"""Narrow privileged USB-only storage for optional P2 profiles.

Unlike report bundles, profiles are separate and never alter prior sessions.
Only USB mounts already verified by usb_store.report_destination() are eligible.
"""
from __future__ import annotations

import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from .p2_profiles import MAX_PROFILE_BYTES, ProfileError, dump_profile_json, load_profile_json
from .report_writer import DIR_FLAGS, FILE_FLAGS, FREE_SPACE_RESERVE
from .usb_store import report_destination

PROFILES_DIR = "PC-Inspector-Profiles"
FILENAME_RE = re.compile(r"profile-[0-9a-f]{32}\.json\Z")
MAX_PROFILES_LISTED = 100


def _dirfd(parent: int, name: str) -> int:
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise RuntimeError("Unsafe profile directory.")
    return fd


def _open_profiles(usb_mount: Path, *, create: bool) -> tuple[int, int]:
    rootfd = os.open(str(usb_mount), DIR_FLAGS)
    try:
        if create:
            try:
                os.mkdir(PROFILES_DIR, 0o700, dir_fd=rootfd)
            except FileExistsError:
                pass
        profilesfd = _dirfd(rootfd, PROFILES_DIR)
        return rootfd, profilesfd
    except Exception:
        os.close(rootfd)
        raise


def _close(rootfd: int, profilesfd: int) -> None:
    os.close(profilesfd)
    os.close(rootfd)


def save_profile(profile: dict) -> dict:
    payload = dump_profile_json(profile).encode("utf-8")
    if len(payload) > MAX_PROFILE_BYTES:
        raise ProfileError("profile too large")
    # Validate first; do not even attempt a mount for rejected data.
    mount = report_destination()
    stats = os.statvfs(mount)
    if stats.f_bavail * stats.f_frsize < len(payload) + FREE_SPACE_RESERVE:
        raise RuntimeError("Insufficient free space on USB.")
    rootfd, profilesfd = _open_profiles(mount, create=True)
    try:
        name = "profile-" + uuid.uuid4().hex + ".json"
        fd = os.open(name, FILE_FLAGS, 0o600, dir_fd=profilesfd)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            readfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=profilesfd)
            with os.fdopen(readfd, "rb") as stream:
                actual = stream.read(MAX_PROFILE_BYTES + 1)
            if actual != payload:
                raise RuntimeError("USB profile readback differs.")
            os.fsync(profilesfd)
        except Exception:
            try:
                os.unlink(name, dir_fd=profilesfd)
            except FileNotFoundError:
                pass
            raise
        os.fsync(rootfd)
    finally:
        _close(rootfd, profilesfd)
    return {"saved": True, "filename": name, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "verification": "readback_sha256_and_fsync"}


def _read_profile(profilesfd: int, filename: str) -> tuple[dict, bytes]:
    if not isinstance(filename, str) or not FILENAME_RE.fullmatch(filename):
        raise ProfileError("invalid profile filename")
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                 dir_fd=profilesfd)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROFILE_BYTES:
            raise ProfileError("invalid profile file")
        raw = stream.read(MAX_PROFILE_BYTES + 1)
    if len(raw) > MAX_PROFILE_BYTES:
        raise ProfileError("profile too large")
    return load_profile_json(raw), raw


def load_profile(filename: str) -> dict:
    # Reject arbitrary paths before any USB discovery/mount.
    if not isinstance(filename, str) or not FILENAME_RE.fullmatch(filename):
        raise ProfileError("invalid profile filename")
    mount = report_destination()
    rootfd, profilesfd = _open_profiles(mount, create=False)
    try:
        profile, raw = _read_profile(profilesfd, filename)
    finally:
        _close(rootfd, profilesfd)
    return {"loaded": True, "filename": filename, "profile": profile,
            "sha256": hashlib.sha256(raw).hexdigest()}


def list_profiles() -> list[dict]:
    mount = report_destination()
    # Empty list is normal if no profile has ever been saved.
    if not (mount / PROFILES_DIR).exists():
        return []
    rootfd, profilesfd = _open_profiles(mount, create=False)
    result = []
    try:
        # Use only names matching our constrained format; do not follow links.
        # Bound directory scanning as well as the returned list (untrusted USB).
        with os.scandir(profilesfd) as entries:
            names = [entry.name for entry in islice(entries, MAX_PROFILES_LISTED * 4)]
        for name in sorted(names):
            if not FILENAME_RE.fullmatch(name):
                continue
            try:
                profile, raw = _read_profile(profilesfd, name)
            except (OSError, ValueError, RuntimeError):
                continue
            result.append({"filename": name, "name": profile["name"],
                           "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()})
            if len(result) >= MAX_PROFILES_LISTED:
                break
    finally:
        _close(rootfd, profilesfd)
    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "root_required"}))
        return 1
    if len(args) not in (1, 2) or args[0] not in ("save", "list", "load"):
        print(json.dumps({"ok": False, "error": "invalid_operation"}))
        return 1
    mode = args[0]
    if (mode == "load") != (len(args) == 2):
        print(json.dumps({"ok": False, "error": "invalid_arguments"}))
        return 1
    try:
        if mode == "save":
            data = sys.stdin.buffer.read(MAX_PROFILE_BYTES + 1)
            profile = load_profile_json(data)
            payload = save_profile(profile)
        elif mode == "list":
            payload = {"profiles": list_profiles()}
        else:
            payload = load_profile(args[1])
        result = {"ok": True, **payload}
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"ok": False, "error": str(exc)[:320]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
