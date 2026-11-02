"""Phone HTTPS bridge: never opens by default, token-gated, TLS-only."""
import json
import ssl
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from inspector.phone_bridge import PhoneBridge


class PhoneTests(unittest.TestCase):
    def test_initially_off_and_no_report(self):
        bridge = PhoneBridge()
        self.assertIsNone(bridge._server)
        self.assertIsNone(bridge.report)

    def test_freezes_report_and_does_not_mutate_provenance(self):
        bridge = PhoneBridge()
        report = {"schema_version": 1, "bios": {"model": "HP 630"}}
        bridge.set_report(report)
        report["bios"]["model"] = "changed"
        self.assertEqual(bridge.report["bios"]["model"], "HP 630")

    def test_private_addresses_are_required(self):
        bridge = PhoneBridge()
        with patch("inspector.phone_bridge.local_ipv4", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "شبكة"):
                bridge.start()

    def test_tls_http_readonly_and_token_denial(self):
        bridge = PhoneBridge()
        bridge.set_report({"schema_version": 1, "bios": {"model": "HP 630"},
                           "purchase_assessment": {"reason": "SMART fail"}})
        with patch("inspector.phone_bridge.local_ipv4", return_value=["127.0.0.1"]):
            data = bridge.start()
        try:
            self.assertTrue(data["url"].startswith("https://"))
            self.assertEqual(len(data["certificate_sha256"]), 64)
            context = ssl._create_unverified_context()  # Unit test only: loopback cert.
            base = data["url"].split("/?", 1)[0]
            with urlopen(base + "/api/report?token=" + bridge.token,
                         context=context, timeout=5) as response:
                parsed = json.loads(response.read())
                self.assertEqual(parsed["bios"]["model"], "HP 630")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with self.assertRaises(HTTPError) as err:
                urlopen(base + "/api/report?token=wrong", context=context, timeout=5)
            self.assertEqual(err.exception.code, 403)
            with urlopen(data["url"], context=context, timeout=5) as response:
                self.assertIn("SMART fail", response.read().decode("utf-8"))
            bridge.set_diagnostics([{"level": "L2", "status": "complete"}])
            with urlopen(base + "/api/session?token=" + bridge.token,
                         context=context, timeout=5) as response:
                self.assertEqual(json.loads(response.read())["diagnostics"][0]["level"], "L2")
        finally:
            previous = bridge.token
            bridge.stop()
            self.assertNotEqual(bridge.token, previous)
            self.assertIsNone(bridge._server)


if __name__ == "__main__":
    unittest.main()
