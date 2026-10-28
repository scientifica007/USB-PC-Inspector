"""Backend regression tests never touch disks or require root."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from inspector import desktop_backend as backend


class DesktopBackendTests(unittest.TestCase):
    def test_single_scan_progress_then_complete(self):
        payload = [
            {"type": "progress", "stage": "identity", "snapshot": {}},
            {"type": "complete", "report": {"schema_version": 1}},
        ]
        process = Mock()
        process.stdout = io.StringIO("".join(
            json.dumps(item) + "\n" for item in payload
        ))
        process.stderr = io.StringIO("")
        process.poll.return_value = 0
        process.wait.return_value = 0
        received = []
        with patch.object(backend.subprocess, "Popen", return_value=process), \
             patch.object(backend.threading, "Timer") as timer:
            backend._stream(["trusted-helper"], lambda *item: received.append(item),
                            False)
        self.assertEqual([item[0] for item in received], ["progress", "complete"])
        self.assertFalse(received[1][1][1])
        timer.return_value.cancel.assert_called_once()

    def test_progress_never_becomes_an_early_verdict(self):
        received = []
        with patch.object(backend.os.path, "isfile", return_value=False), \
             patch.object(backend, "_stream") as run:
            backend.collect_l1(lambda *item: received.append(item))
        self.assertEqual(run.call_count, 1)
        self.assertTrue(run.call_args.args[2])  # limited privileges
        self.assertEqual(received, [])

    def test_privilege_failure_resets_then_retries_once(self):
        received = []
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.shutil, "which", return_value="/usr/bin/sudo"), \
             patch.object(backend, "_stream",
                          side_effect=[RuntimeError("no sudo"), None]) as runner:
            backend.collect_l1(lambda *item: received.append(item))
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(received, [("reset", None)])

    def test_timeout_does_not_retry_privileged_scan(self):
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.shutil, "which", return_value="/usr/bin/sudo"), \
             patch.object(backend, "_stream",
                          side_effect=TimeoutError("expired")) as runner:
            with self.assertRaises(TimeoutError):
                backend.collect_l1(lambda *item: None)
        runner.assert_called_once()

    def test_save_does_not_rescan_and_returns_valid_receipt(self):
        report = {"schema_version": 1}
        success = Mock(returncode=0,
                       stdout=json.dumps({"saved": True, "json": "/usb/report.json"}))
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.subprocess, "run", return_value=success) as saved, \
             patch.object(backend, "_stream") as scanned:
            receipt = backend.save_to_usb(report)
        self.assertTrue(receipt["saved"])
        scanned.assert_not_called()
        self.assertEqual(saved.call_args.args[0][-1], backend.SAVE_HELPER)

    def test_failed_save_retains_caller_report_and_can_retry(self):
        report = {"schema_version": 1, "storage": [{"test": True}]}
        failure = Mock(returncode=1, stdout='{"saved":false,"error":"no USB"}')
        success = Mock(returncode=0, stdout='{"saved":true,"json":"/usb/r.json"}')
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.subprocess, "run",
                          side_effect=[failure, success]):
            with self.assertRaisesRegex(RuntimeError, "no USB"):
                backend.save_to_usb(report)
            receipt = backend.save_to_usb(report)
        self.assertTrue(receipt["saved"])
        self.assertEqual(report, {"schema_version": 1, "storage": [{"test": True}]})

    def test_lying_success_with_nonzero_exit_is_rejected(self):
        fake = Mock(returncode=1, stdout='{"saved":true}')
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.subprocess, "run", return_value=fake):
            with self.assertRaises(RuntimeError):
                backend.save_to_usb({"schema_version": 1})

    def test_bad_receipt_is_not_saved(self):
        fake = Mock(returncode=0, stdout="not json")
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "إيصال"):
                backend.save_to_usb({"schema_version": 1})

    def test_invalid_save_input_never_invokes_sudo(self):
        with patch.object(backend.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                backend.save_to_usb({"schema_version": 2})
            run.assert_not_called()


    def test_two_completed_scans_can_be_saved_without_implicit_rescan(self):
        first = {"schema_version": 1, "bios": {"model": "one"}}
        second = {"schema_version": 1, "bios": {"model": "two"}}
        receipts = [
            Mock(returncode=0, stdout='{"saved":true,"json":"/usb/session-1/report.json"}'),
            Mock(returncode=0, stdout='{"saved":true,"json":"/usb/session-2/report.json"}'),
        ]
        with patch.object(backend.os.path, "isfile", return_value=True), \
             patch.object(backend.subprocess, "run", side_effect=receipts) as saver, \
             patch.object(backend, "_stream") as collector:
            receipt_a = backend.save_to_usb(first)
            receipt_b = backend.save_to_usb(second)
        self.assertNotEqual(receipt_a["json"], receipt_b["json"])
        self.assertEqual(saver.call_count, 2)
        sent = [json.loads(call.kwargs["input"])["bios"]["model"]
                for call in saver.call_args_list]
        self.assertEqual(sent, ["one", "two"])
        collector.assert_not_called()

if __name__ == "__main__":
    unittest.main()
