"""Non-graphical protocol tests for the Arabic desktop interface."""
import io
import json
import queue
import unittest
from unittest.mock import Mock, patch

try:
    from inspector import gui
except ImportError:
    gui = None


@unittest.skipIf(gui is None, "tkinter not installed")
class GuiProtocolTests(unittest.TestCase):
    def test_preview_does_not_claim_purchase_decision(self):
        event = {"stage": "identity", "elapsed_seconds": 0.25,
                 "message": "تم جرد الجهاز",
                 "snapshot": {"bios": {"manufacturer": "Demo"},
                              "cpu": {"model": "Demo CPU"}}}
        text = gui.InspectorApp.format_progress(event)
        self.assertIn("Demo CPU", text)
        self.assertIn("القرار النهائي لم يصدر بعد", text)
        self.assertNotIn("لا يُنصح بالشراء", text)
        self.assertIn("\n", text)

    def test_date_display_is_day_month_year(self):
        self.assertEqual(
            gui.InspectorApp.display_date("2026-10-27T14:04:00+00:00"),
            "27/10/2026 14:04 UTC",
        )

    def test_progress_then_complete_messages(self):
        app = gui.InspectorApp.__new__(gui.InspectorApp)
        app.events = queue.Queue()
        payload = [
            {"type": "progress", "stage": "identity", "snapshot": {}},
            {"type": "complete", "report": {"schema_version": 1}},
        ]
        process = Mock()
        process.stdout = io.StringIO("".join(json.dumps(x) + "\n" for x in payload))
        process.stderr = io.StringIO("")
        process.poll.return_value = 0
        process.wait.return_value = 0
        with patch.object(gui.subprocess, "Popen", return_value=process):
            app._stream_collect(["fake"], True)
        self.assertEqual(app.events.get_nowait()[0], "progress")
        event = app.events.get_nowait()
        self.assertEqual(event[0], "scan")
        self.assertTrue(event[2])


if __name__ == "__main__":
    unittest.main()
