"""Exercise the real helper protocol without opening a desktop surface."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OverlayProcess:
    def __init__(self, process):
        self.process = process
        self.buffer = b""

    def send(self, state, profile="MIX"):
        self.process.stdin.write((json.dumps({"state": state, "profile": profile}) + "\n").encode())
        self.process.stdin.flush()

    def read(self, timeout=3):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError("No popup status report")
            data = os.read(self.process.stdout.fileno(), 4096)
            if not data:
                raise AssertionError("Popup helper exited before reporting status")
            self.buffer += data
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)


@contextmanager
def overlay():
    with tempfile.TemporaryDirectory(prefix="phimthai-overlay-test-") as temporary:
        environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR="1",
                           QT_SCREEN_SCALE_FACTORS="1", QT_AUTO_SCREEN_SCALE_FACTOR="0",
                           XDG_RUNTIME_DIR=temporary, DISPLAY="", WAYLAND_DISPLAY="")
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                [sys.executable, "-c", "from phimthai.feedback import _overlay; "
                 "raise SystemExit(_overlay(_allow_headless=True))"],
                cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errors)
            helper = OverlayProcess(process)
            try:
                ready = helper.read(10)
                if ready != {"event": "ready", "platform": "offscreen"}:
                    raise AssertionError(ready)
                yield helper
            finally:
                if process.poll() is None:
                    if not process.stdin.closed:
                        try:
                            helper.send("shutdown")
                        except BrokenPipeError:
                            pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                for stream in (process.stdin, process.stdout):
                    if not stream.closed:
                        stream.close()


class FeedbackOverlayTests(unittest.TestCase):
    def assert_hidden(self, report, state="idle"):
        self.assertEqual(report["event"], "state")
        self.assertEqual(report["state"], state)
        self.assertFalse(report["visible"])
        self.assertFalse(report["focused"])

    def test_cancel_processing_and_shutdown_report_hidden(self):
        with overlay() as helper:
            # Even the initial idle state must report false focus without a window handle.
            helper.send("idle")
            self.assert_hidden(helper.read())
            helper.send("processing")
            processing = helper.read()
            self.assertEqual(processing["state"], "processing")
            self.assertTrue(processing["visible"])
            self.assertFalse(processing["focused"])
            self.assertEqual((processing["x"], processing["width"], processing["height"]),
                             (32, 200, 52))
            helper.send("idle", "RAW")
            canceled = helper.read()
            self.assert_hidden(canceled)
            self.assertEqual(canceled["profile"], "RAW")
            helper.send("shutdown")
            self.assert_hidden(helper.read(), "shutdown")
            self.assertEqual(helper.process.wait(timeout=2), 0)

    def test_error_timeout_reports_hidden(self):
        with overlay() as helper:
            helper.send("error", "TH>ENG")
            shown = helper.read()
            self.assertTrue(shown["visible"])
            self.assertEqual(shown["state"], "error")
            hidden = helper.read(7)
            self.assert_hidden(hidden)
            self.assertEqual(hidden["profile"], "TH>ENG")
            self.assertIsNone(helper.process.poll())

    def test_new_processing_cancels_previous_auto_hide(self):
        with overlay() as helper:
            helper.send("success")
            self.assertEqual(helper.read()["state"], "success")
            helper.send("processing")
            self.assertTrue(helper.read()["visible"])
            with self.assertRaises(TimeoutError):
                helper.read(2.3)
            helper.send("idle")
            self.assert_hidden(helper.read())

    def test_closed_input_reports_shutdown_and_reaps_helper(self):
        with overlay() as helper:
            helper.send("processing")
            self.assertTrue(helper.read()["visible"])
            helper.process.stdin.close()
            self.assert_hidden(helper.read(), "shutdown")
            self.assertEqual(helper.process.wait(timeout=2), 0)


if __name__ == "__main__":
    unittest.main()
