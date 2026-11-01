"""Read an explicitly selected buyer profile file, never write to target disks.

Only small, regular non-symlink files can be imported. This is an optional
user action, not part of automatic L1 or the root USB storage helper.
"""
from __future__ import annotations

import os
import stat

from .p2_profiles import MAX_PROFILE_BYTES, ProfileError, load_profile_json


def import_profile_file(path: str) -> dict:
    if not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path:
        raise ProfileError("invalid import path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ProfileError("profile must be a regular file")
        if info.st_size > MAX_PROFILE_BYTES:
            raise ProfileError("profile too large")
        raw = source.read(MAX_PROFILE_BYTES + 1)
    return load_profile_json(raw)
