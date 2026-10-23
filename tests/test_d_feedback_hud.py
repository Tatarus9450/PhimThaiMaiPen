"""HUD states, level throttling, and helper rendering without a desktop surface."""
import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from phimthai import feedback
from phimthai.feedback import DictationFeedback, LEVEL_INTERVAL
from tests.test_feedback_overlay import overlay


def app():
    return QApplication.instance() or QApplication([])


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class ControllerTests(unittest.TestCase):
    def setUp(self):
        app()
        self.feedback = DictationFeedback(sound_enabled=True, popup_enabled=True, reduced_motion=False)
        self.addCleanup(self.feedback.shutdown)
        self.sent = []
        original = self.feedback._send
        self.feedback._send = lambda payload: (self.sent.append(payload), original(payload))
        self.played = []
        self.feedback._play = self.played.append
        self.clock = Clock()
        self.feedback._clock = self.clock

    @property
    def payload(self):
        return self.feedback.last_payload

    def test_new_states_produce_expected_payloads(self):
        fb = self.feedback
        fb.preparing()
        self.assertEqual((self.payload["state"], self.payload["message"]), ("preparing", "กำลังเตรียมโมเดล…"))
        fb.model_ready()
        self.assertEqual(self.payload["state"], "idle")
        fb.queued(2)
        self.assertEqual((self.payload["state"], self.payload["count"], self.payload["message"]),
                         ("queued", 2, "รอคิว 2 งาน"))
        fb.pasted()
        self.assertEqual((self.payload["state"], self.payload["message"]), ("pasted", "วางแล้ว"))
        fb.copied()
        self.assertEqual((self.payload["state"], self.payload["message"]),
                         ("copied", "คัดลอกแล้ว · กด Ctrl+V เพื่อวาง"))
        fb.copied("Custom hint")
        self.assertEqual(self.payload["message"], "Custom hint")
        self.assertEqual(fb._phase, "copied")

    def test_error_with_hint_and_legacy_single_argument(self):
        self.feedback.error("ไมโครโฟน   ไม่ตอบสนอง\n")
        self.assertEqual((self.payload["state"], self.payload["message"], self.payload["hint"]),
                         ("error", "ไมโครโฟน ไม่ตอบสนอง", ""))
        self.feedback.error("วางไม่ได้", hint="เปิดสิทธิ์ในหน้าตั้งค่า")
        self.assertEqual((self.payload["message"], self.payload["hint"]), ("วางไม่ได้", "เปิดสิทธิ์ในหน้าตั้งค่า"))
        self.feedback.error("x" * 500)
        self.assertEqual(len(self.payload["message"]), 220)

    def test_preparing_while_listening_is_a_secondary_line(self):
        fb = self.feedback
        fb.listening()
        fb.preparing()
        self.assertEqual(self.payload["state"], "listening")
        self.assertEqual(self.payload["detail"], "โมเดลกำลังโหลด พูดต่อได้เลย")
        fb.tick(3)
        self.assertEqual((self.payload["seconds"], self.payload["detail"]), (3, "โมเดลกำลังโหลด พูดต่อได้เลย"))
        fb.processing()
        self.assertEqual((self.payload["state"], self.payload["detail"]), ("processing", "โมเดลกำลังโหลด…"))
        fb.model_ready()
        self.assertEqual(self.payload["state"], "processing")
        self.assertNotIn("detail", self.payload)
        fb.model_ready()  # Idempotent: no extra message.
        self.assertEqual(len([p for p in self.sent if p["state"] == "processing"]), 2)

    def test_preparing_before_listening_keeps_hint_once_listening(self):
        self.feedback.preparing("โหลด")
        self.feedback.listening()
        self.assertEqual((self.payload["state"], self.payload["detail"]), ("listening", "โมเดลกำลังโหลด พูดต่อได้เลย"))
        self.feedback.model_ready()
        self.assertEqual(self.payload["state"], "listening")
        self.assertNotIn("detail", self.payload)

    def test_level_is_throttled_to_fifteen_per_second_with_trailing_value(self):
        fb = self.feedback
        fb.level(50)
        self.assertFalse(self.sent, "No level traffic outside listening")
        fb.listening()
        self.sent.clear()
        for value in range(0, 100, 10):
            fb.level(value)
            self.clock.now += 0.005
        self.assertEqual(len(self.sent), 0, "listening() just sent; first levels are inside the window")
        self.assertTrue(fb._level_timer.isActive())
        self.clock.now += LEVEL_INTERVAL
        wait(int(LEVEL_INTERVAL * 1000) + 40)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[-1]["level"], 90, "Trailing send carries the latest level")
        # One simulated second of 100 Hz updates sends no more than 15 messages.
        self.sent.clear()
        fb._level_timer.stop()
        for step in range(100):
            fb.level(step % 101)
            self.clock.now += 0.01
        self.assertLessEqual(len(self.sent), 15)
        self.assertGreaterEqual(len(self.sent), 10)
        fb.level(250)
        fb.tick(1)
        self.assertEqual(self.payload["level"], 100)
        fb.cancel()
        wait(int(LEVEL_INTERVAL * 1000) + 30)
        self.assertEqual(self.payload["state"], "idle", "A pending level flush cannot revive the HUD")

    def test_ready_chime_plays_once_per_delivery(self):
        fb = self.feedback
        fb.listening()
        fb.processing()
        fb.typing()
        fb.pasted()
        fb.copied()
        self.assertEqual(self.played, ["start", "stop", "ready"])
        fb.processing()
        fb.pasted()
        self.assertEqual(self.played[-1], "ready")
        self.assertEqual(self.played.count("ready"), 2)
        fb.listening()
        fb.queued(1)
        self.assertEqual(self.played[-2:], ["start", "stop"])

    def test_reduced_motion_and_profile_rerender_keep_fields(self):
        fb = self.feedback
        fb.error("ผิด", hint="ลองใหม่")
        fb.configure(reduced_motion=True)
        self.assertTrue(self.payload["reduced_motion"])
        self.assertEqual((self.payload["state"], self.payload["hint"]), ("error", "ลองใหม่"))
        fb.set_profile("raw")
        self.assertEqual((self.payload["profile"], self.payload["message"]), ("RAW", "ผิด"))
        fb.configure(popup_enabled=False)
        self.assertEqual(self.payload["state"], "idle")

    def test_reduced_motion_from_environment(self):
        os.environ["PHIMTHAI_REDUCED_MOTION"] = "1"
        self.addCleanup(os.environ.pop, "PHIMTHAI_REDUCED_MOTION", None)
        other = DictationFeedback(popup_enabled=True)
        self.addCleanup(other.shutdown)
        self.assertTrue(other.reduced_motion)
        other.listening()
        self.assertTrue(other.last_payload["reduced_motion"])

    def test_closed_controller_ignores_new_methods(self):
        self.feedback.shutdown()
        for call in (lambda: self.feedback.preparing(), self.feedback.model_ready,
                     lambda: self.feedback.level(5), self.feedback.pasted,
                     lambda: self.feedback.copied(), lambda: self.feedback.queued(1),
                     lambda: self.feedback.error("x", "y")):
            call()
        self.assertEqual(self.sent, [])


class HelperTests(unittest.TestCase):
    @staticmethod
    def send(helper, **payload):
        payload.setdefault("profile", "MIX")
        helper.process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        helper.process.stdin.flush()
        return helper.read()

    def test_helper_reports_new_states(self):
        with overlay() as helper:
            shown = self.send(helper, state="listening", seconds=7, level=42,
                              detail="โมเดลกำลังโหลด พูดต่อได้เลย")
            self.assertEqual((shown["state"], shown["seconds"], shown["level"]), ("listening", 7, 42))
            self.assertEqual(shown["detail"], "โมเดลกำลังโหลด พูดต่อได้เลย")
            self.assertTrue(shown["animated"])
            self.assertFalse(shown["focused"])
            self.assertEqual((shown["x"], shown["width"], shown["height"]), (32, 240, 52))
            still = self.send(helper, state="listening", reduced_motion=True)
            self.assertFalse(still["animated"])
            error = self.send(helper, state="error", message="วางไม่ได้", hint="กด Ctrl+V เอง")
            self.assertEqual((error["title"], error["detail"], error["animated"]),
                             ("วางไม่ได้", "กด Ctrl+V เอง", False))
            copied = self.send(helper, state="copied", message="คัดลอกแล้ว · กด Ctrl+V เพื่อวาง")
            self.assertEqual((copied["title"], copied["detail"]), ("คัดลอกแล้ว", "กด Ctrl+V เพื่อวาง"))
            queued = self.send(helper, state="queued", message="รอคิว 3 งาน", count=3)
            self.assertEqual((queued["title"], queued["count"]), ("รอคิว 3 งาน", 3))
            preparing = self.send(helper, state="preparing", message="กำลังเตรียมโมเดล…")
            self.assertTrue(preparing["visible"])
            pasted = self.send(helper, state="pasted", message="วางแล้ว")
            self.assertEqual(pasted["title"], "วางแล้ว")
            hidden = helper.read(3)
            self.assertEqual((hidden["state"], hidden["visible"]), ("idle", False))

    def test_garbage_lines_do_not_kill_helper(self):
        with overlay() as helper:
            helper.process.stdin.write(b"[1, 2]\nnot json\n")
            helper.process.stdin.flush()
            shown = self.send(helper, state="processing", level="loud")
            self.assertTrue(shown["visible"])


class RenderTests(unittest.TestCase):
    def test_render_every_state_and_elide_long_thai(self):
        application = app()
        widget = feedback._make_overlay(application)
        self.addCleanup(widget.deleteLater)
        long = "ไม่สามารถวางข้อความลงในหน้าต่างปลายทางได้เพราะสิทธิ์การควบคุมแป้นพิมพ์หมดอายุแล้ว" * 2
        payloads = [dict(state="listening", seconds=65, level=60, detail="โมเดลกำลังโหลด พูดต่อได้เลย"),
                    dict(state="preparing", message="กำลังเตรียมโมเดล…"),
                    dict(state="processing"), dict(state="queued", message="รอคิว 2 งาน", count=2),
                    dict(state="pasted", message="วางแล้ว"), dict(state="typing"),
                    dict(state="copied", message="คัดลอกแล้ว · กด Ctrl+V เพื่อวาง"),
                    dict(state="error", message=long, hint=long), dict(state="mode", profile="TH>ENG")]
        output = os.environ.get("PHIMTHAI_HUD_SHOT_DIR")
        for payload in payloads:
            with self.subTest(state=payload["state"]):
                payload.setdefault("profile", "MIX")
                widget.apply(payload)
                image = widget.grab().toImage()
                self.assertEqual((image.width(), image.height()), (240, 52))
                if output:
                    image.save(os.path.join(output, "hud-%s.png" % payload["state"]))
        self.assertLess(widget.elided(long, widget.title_font, 150).__len__(), len(long))
        self.assertTrue(widget.elided(long, widget.title_font, 150).endswith("…"))


if __name__ == "__main__":
    unittest.main()
