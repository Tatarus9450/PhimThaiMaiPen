"""Main-window integration: state, debounce, queueing, saved settings, paste fallback."""
import json
import unittest
from collections import deque
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QGuiApplication

from phimthai import strings as S
from phimthai.settings import Settings, config_path, load_settings
from phimthai.state import Debouncer, DictationState, derive_state
from tests.test_app_review import IsolatedWindow
from tests.test_feedback_flow import InertClipboard, InertRecorder


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class StateModuleTests(unittest.TestCase):
    def test_debouncer_accepts_once_per_interval_and_reset(self):
        clock = FakeClock()
        debounce = Debouncer(0.4, clock)
        self.assertTrue(debounce.accept())
        clock.now += 0.05
        self.assertFalse(debounce.accept())
        clock.now += 0.4
        self.assertTrue(debounce.accept())
        debounce.reset()
        self.assertTrue(debounce.accept())

    def test_state_precedence(self):
        self.assertIs(derive_state(), DictationState.IDLE)
        self.assertIs(derive_state(processing=True), DictationState.PROCESSING)
        self.assertIs(derive_state(processing=True, pasting=True), DictationState.PASTING)
        self.assertIs(derive_state(recording=True, pasting=True, processing=True), DictationState.RECORDING)


class StringsTests(unittest.TestCase):
    def test_no_empty_user_strings(self):
        values = S.all_strings()
        self.assertGreater(len(values), 100)
        for name, value in values.items():
            with self.subTest(name=name):
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip(), f"{name} is empty")

    def test_known_job_messages_become_thai(self):
        self.assertEqual(S.job_message("Ready"), S.STATUS_IDLE)
        self.assertEqual(S.job_message("Cancelled"), S.STATUS_CANCELLED)
        self.assertEqual(S.job_message("Speech worker stopped unexpectedly (9). You can retry."),
                         S.JOB_STATUS["Speech worker stopped unexpectedly"])
        self.assertEqual(S.job_message("ข้อความไทย"), "ข้อความไทย")


class WindowTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        with patch("phimthai.app.Recorder", InertRecorder):
            super().setUp()
        self.window.clipboard = InertClipboard()
        self.window.clipboard.restored.connect(self.window.clipboard_restored)
        self.clock = FakeClock()
        self.window.toggle_debounce.clock = self.clock
        model = patch("phimthai.app.local_model", return_value=self.root / "synthetic-model")
        model.start()
        self.addCleanup(model.stop)
        self.commands = []
        self.window.portal = SimpleNamespace(write=lambda raw: self.commands.append(json.loads(raw)),
                                             readAllStandardOutput=lambda: b"")
        self.addCleanup(setattr, self.window, "portal", None)

    def advance(self, seconds=0.5):
        self.clock.now += seconds

    def test_double_hotkey_within_debounce_does_not_stop_recording(self):
        self.window.toggle_record()
        self.assertTrue(self.window.recording)
        self.assertIs(self.window.state, DictationState.RECORDING)
        self.advance(0.05)
        self.window.toggle_record()  # Duplicate Meta+H from a second binding.
        self.assertTrue(self.window.recording)
        self.window.jobs.submit.assert_not_called()
        self.advance(0.5)
        self.window.toggle_record()
        self.assertFalse(self.window.recording)
        self.window.jobs.submit.assert_called_once()

    def test_record_while_processing_queues_and_reports_queue(self):
        self.window.jobs = Mock(busy=True, pending=deque(), active={"action": "transcribe", "audio": "/x.wav"},
                                warm=True)
        self.assertIs(self.window.state, DictationState.PROCESSING)
        queued = Mock()
        self.window.feedback.queued = queued
        self.window.toggle_record()
        self.assertTrue(self.window.recording, "A running job must not block a new recording")
        self.assertEqual(self.window.status.text(), S.STATUS_LISTENING_QUEUED)
        self.window.jobs.prewarm.assert_called_once_with(self.window.settings)
        self.advance()
        self.window.toggle_record()
        self.window.jobs.submit.assert_called_once()
        queued.assert_called_once_with(1)
        self.assertEqual(self.window.status.text(), S.STATUS_QUEUED.format(count=1))

    def test_full_queue_refuses_to_start_recording(self):
        self.window.jobs = Mock(busy=True, pending=deque([{}, {}, {}, {}]), active=None)
        self.window.toggle_record()
        self.assertFalse(self.window.recording)
        self.assertIn(S.ERR_QUEUE_FULL, self.window.status.text())

    def test_cold_model_shows_preparing_then_ready(self):
        self.window.jobs = Mock(busy=False, pending=deque(), active=None, warm=False)
        preparing, ready = Mock(), Mock()
        self.window.feedback.preparing = preparing
        self.window.feedback.model_ready = ready
        self.window.toggle_record()
        preparing.assert_called_once()
        self.assertEqual(self.window.status.text(), S.STATUS_PREPARING)
        self.window.warm_changed(True)
        ready.assert_called_once()
        self.assertEqual(self.window.status.text(), S.STATUS_LISTENING)
        self.window.cancel()

    def test_recording_uses_saved_settings_not_unsaved_invalid_form(self):
        self.window.hotkey.setText("not a hotkey !!!")
        self.window.paste_mode.setCurrentIndex(self.window.paste_mode.findData("review"))
        with patch.object(self.window, "current_settings", side_effect=ValueError("invalid form")):
            self.window.toggle_record()
            self.assertTrue(self.window.recording)
            self.assertIs(self.window.record_settings, self.window.settings)
            self.advance()
            self.window.toggle_record()
        submitted = self.window.jobs.submit.call_args.args[0]
        self.assertEqual(submitted.hotkey, "Meta+H")
        self.assertEqual(submitted.paste_mode, "immediate")

    def test_failed_clipboard_offer_falls_back_to_copy(self):
        self.window.paste_enabled = True
        self.window.clipboard.offer = Mock(return_value=False)
        copied = Mock()
        self.window.feedback.copied = copied
        self.window.editor.setPlainText("ข้อความทดสอบ")
        self.window.paste(automatic=True)
        self.assertFalse(self.window.paste_timer.isActive())
        self.assertFalse(self.window.paste_busy)
        copied.assert_called_once()
        self.assertEqual(QGuiApplication.clipboard().text(), "ข้อความทดสอบ")
        self.assertEqual(self.window.status.text(), S.COPIED_FALLBACK)
        self.assertEqual(self.commands, [])

    def test_missing_paste_permission_copies_instead_of_error(self):
        self.window.paste_enabled = False
        copied = Mock()
        self.window.feedback.copied = copied
        result = {"id": "r", "text": "synthetic", "settings": asdict(Settings(paste_mode="immediate"))}
        self.window.completed(result)
        copied.assert_called_once()
        self.assertNotIn(S.ERROR_PREFIX, self.window.status.text())
        self.assertEqual(self.window.clipboard.offers, [])

    def test_manual_paste_shows_countdown_and_escape_cancels(self):
        self.window.paste_enabled = True
        self.window.editor.setPlainText("synthetic")
        with patch.object(self.window, "isActiveWindow", return_value=True):
            self.window.paste()
        self.assertTrue(self.window.paste_timer.isActive())
        self.assertEqual(self.window.status.text(), S.PASTE_COUNTDOWN.format(seconds=3))
        self.assertIs(self.window.state, DictationState.PASTING)
        self.window.escape_pressed()
        self.assertFalse(self.window.paste_timer.isActive())
        self.assertFalse(self.window.paste_busy)
        self.assertEqual(self.window.status.text(), S.PASTE_CANCELLED)
        self.assertIs(self.window.state, DictationState.IDLE)
        self.assertEqual(self.commands, [])

    def test_escape_discards_recording(self):
        self.window.toggle_record()
        audio = self.window.audio_path
        audio.write_bytes(b"x")
        self.window.escape_pressed()
        self.assertFalse(self.window.recording)
        self.assertFalse(audio.exists())
        self.window.jobs.submit.assert_not_called()

    def test_paste_sent_uses_pasted_feedback(self):
        self.window.paste_enabled = True
        pasted = Mock()
        self.window.feedback.pasted = pasted
        self.window.editor.setPlainText("synthetic")
        self.window.paste()
        self.window.paste_timer.stop()
        self.window.send_paste()
        request = self.window.paste_request_id
        self.window.portal.readAllStandardOutput = lambda: (json.dumps(
            {"event": "paste_sent", "request_id": request}) + "\n").encode()
        self.window.portal_output()
        pasted.assert_called_once()

    def test_error_jumps_only_for_dictation(self):
        with patch.object(self.window, "isVisible", return_value=True):
            self.window.nav.setCurrentRow(2)
            self.window.error("settings problem")
            self.assertEqual(self.window.nav.currentRow(), 2)
            self.window.error("dictation problem", jump=True)
            self.assertEqual(self.window.nav.currentRow(), 0)
        with patch.object(self.window, "isVisible", return_value=False):
            self.window.nav.setCurrentRow(2)
            self.window.error("hidden dictation problem", jump=True)
            self.assertEqual(self.window.nav.currentRow(), 2, "Hidden windows rely on the HUD")

    def test_english_job_status_is_shown_in_thai(self):
        self.window.job_status_changed("Cancelled")
        self.assertEqual(self.window.status.text(), S.STATUS_CANCELLED)
        self.window.job_failed("Speech processing timed out. Retry with a shorter recording or another model.")
        self.assertIn(S.JOB_STATUS["Speech processing timed out"], self.window.status.text())

    def test_cleanup_keeps_live_recording_and_queued_audio(self):
        self.window.toggle_record()
        live = self.window.audio_path
        live.write_bytes(b"live")
        queued = self.audio("queued.wav")
        stale = self.audio("stale.wav")
        self.window.jobs.pending = deque([{"action": "transcribe", "audio": str(queued)}])
        self.window.cleanup_temporary_audio()
        self.assertTrue(live.exists())
        self.assertTrue(queued.exists())
        self.assertFalse(stale.exists())
        self.window.cancel()

    def test_status_report_keeps_keys_and_adds_state(self):
        report = self.window.status_report()
        for key in ("running", "pid", "version", "recording", "busy", "transcript_characters", "shortcut",
                    "mode_shortcut", "profile", "visible", "paste_mode", "paste_enabled",
                    "permission_pending", "popup", "popup_error", "status"):
            self.assertIn(key, report)
        self.assertEqual(report["state"], "idle")
        json.dumps(report)

    def test_copy_diagnostic_report_passes_extra(self):
        captured = {}

        def report(extra=None):
            captured.update(extra)
            return "REPORT"

        with patch("phimthai.logs.diagnostic_report", side_effect=report, create=True):
            self.window.copy_diagnostic_report()
        self.assertEqual(QGuiApplication.clipboard().text(), "REPORT")
        for key in ("shortcut", "paste_enabled", "model", "warm", "state"):
            self.assertIn(key, captured)
        self.assertEqual(self.window.status.text(), S.STATUS_REPORT_COPIED)

    def test_tray_tooltip_follows_state(self):
        tray = Mock()
        self.window.tray = tray
        self.window.toggle_record()
        tray.setToolTip.assert_called_with(S.TRAY_RECORDING)
        self.window.cancel()
        tray.setToolTip.assert_called_with(S.TRAY_IDLE)
        self.window.tray = None


class SettingsRepairTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        pass  # Each test constructs its own window around a patched loader.

    def build(self, loader):
        with patch("phimthai.app.load_settings_with_report", loader):
            IsolatedWindow.setUp(self)

    def test_repaired_settings_are_saved_reported_and_do_not_block_first_run(self):
        self.build(Mock(return_value=(Settings(profile="raw"), ["ตั้งค่า device ไม่ถูกต้อง ใช้ค่าเริ่มต้นแทน"])))
        self.assertEqual(self.window.settings_error, "")
        self.assertIn("ตั้งค่า device ไม่ถูกต้อง", self.window.status.text())
        self.assertTrue(config_path().exists())
        self.assertEqual(load_settings().profile, "raw")
        self.window.continue_desktop_setup = Mock()
        with patch("phimthai.app.local_model", return_value=self.root):
            self.window.start_first_run()
        self.assertTrue(self.window.startup_started)

    def test_unsupported_version_blocks_first_run_without_overwriting(self):
        self.build(Mock(side_effect=ValueError("unsupported application version")))
        self.assertIn("unsupported application version", self.window.settings_error)
        self.assertFalse(config_path().exists())
        self.window.start_first_run()
        self.assertFalse(self.window.startup_started)


if __name__ == "__main__":
    unittest.main()
