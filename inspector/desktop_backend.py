"""UI-independent bridge to the existing allowlisted L1 collector and USB writer.

Both operations are intended for worker threads; the frontend marshals results
back onto its UI thread. Never writes to internal disks or launches arbitrary
shell commands.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable

COLLECT_HELPER = "/usr/local/bin/pc-inspector-collect"
SAVE_HELPER = "/usr/local/bin/pc-inspector-save"
MAX_SCANNER_SECONDS = 90


def _stream(
    argv: list[str], emit: Callable[[str, Any], None], reduced: bool,
) -> None:
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    timed_out = threading.Event()

    def kill_when_expired() -> None:
        if proc.poll() is None:
            timed_out.set()
            proc.kill()

    timer = threading.Timer(MAX_SCANNER_SECONDS, kill_when_expired)
    timer.daemon = True
    timer.start()
    complete = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise RuntimeError("رد غير صالح من محرك الفحص.") from exc
            if not isinstance(event, dict):
                raise RuntimeError("بنية بيانات الفحص غير صحيحة.")
            if event.get("type") == "progress":
                emit("progress", event)
            elif event.get("type") == "complete":
                complete = event.get("report")
            else:
                raise RuntimeError("نوع حدث الفحص غير معروف.")
        assert proc.stderr is not None
        stderr = proc.stderr.read()[-750:]
        code = proc.wait()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
    if timed_out.is_set():
        raise TimeoutError("انتهت مهلة الفحص (90 ثانية).")
    if code != 0 or not isinstance(complete, dict):
        raise RuntimeError(stderr or "لم يكتمل الفحص أو لم يصدر تقرير صالح.")
    emit("complete", (complete, reduced))


def collect_l1(emit: Callable[[str, Any], None]) -> None:
    """Execute one scan; retry unprivileged only on helper failure, not timeout."""
    if os.path.isfile(COLLECT_HELPER) and shutil.which("sudo"):
        try:
            _stream(["sudo", "-n", COLLECT_HELPER, "--events"], emit, False)
            return
        except TimeoutError:
            # Python TimeoutError is an OSError subclass; never repeat a timed-out scan.
            raise
        except (OSError, RuntimeError):
            emit("reset", None)
    _stream([sys.executable, "-m", "inspector.core", "--events"], emit, True)


def save_to_usb(report: dict[str, Any]) -> dict[str, Any]:
    """Save an already completed report; never rerun the hardware scan."""
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("لا يوجد تقرير صالح لحفظه.")
    if not os.path.isfile(SAVE_HELPER):
        raise RuntimeError("مساعد الحفظ على USB غير موجود.")
    result = subprocess.run(
        ["sudo", "-n", SAVE_HELPER],
        input=json.dumps(report, ensure_ascii=False),
        capture_output=True, text=True, timeout=50, check=False,
    )
    try:
        receipt = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("لم يرسل مساعد الحفظ إيصالًا صالحًا.") from exc
    if not isinstance(receipt, dict) or receipt.get("saved") is not True or result.returncode != 0:
        detail = receipt.get("error") if isinstance(receipt, dict) else None
        raise RuntimeError(str(detail or "لم يكتمل حفظ التقرير على USB."))
    return receipt
