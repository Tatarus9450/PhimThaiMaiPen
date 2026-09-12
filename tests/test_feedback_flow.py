"""Headless dictation/paste integration with inert microphone and clipboard."""
import json
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_app_review import IsolatedWindow
from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtTest import QTest


class InertMediaDevices(QObject):
    audioInputsChanged = Signal()


class InertRecorder(QObject):
    failed = Signal(str)
    level = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.media_devices = InertMediaDevices(self)

    def start(self, *_args):
        pass

    def stop(self):
        return True


class InertClipboard(QObject):
    restored = Signal()

    def __init__(self):
        super().__init__()
        self.owned = False
        self.offers = []
        self.restore_requests = 0

    def offer(self, text):
        self.offers.append(text)
        self.owned = True

    def owns_clipboard(self):
        return self.owned

    def restore(self):
        if self.owned:
            self.owned = False
            self.restored.emit()

    def restore_later(self):
        self.restore_requests += 1


class FeedbackFlowTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        with patch("phimthai.app.Recorder", InertRecorder):
            super().setUp()
        self.window.clipboard = InertClipboard()
        self.window.clipboard.restored.connect(self.window.clipboard_restored)
        self.addCleanup(self.window.clipboard.restore)
        self.commands = []
        self.responses = b""
        self.window.portal = SimpleNamespace(
            write=lambda raw: self.commands.append(json.loads(raw)),
            readAllStandardOutput=self.read_response,
        )
        self.addCleanup(setattr, self.window, "portal", None)
        self.window.paste_enabled = True
        self.window.paste_mode.setCurrentIndex(self.window.paste_mode.findData("immediate"))
        self.assertFalse(self.window.feedback.sound_enabled)
        self.assertFalse(self.window.feedback.popup_enabled)
        self.assertEqual(self.window.feedback.process.state(), QProcess.ProcessState.NotRunning)

    def read_response(self):
        response, self.responses = self.responses, b""
        return response

    def acknowledge_paste(self, request_id=None):
        self.responses = (json.dumps({"event": "paste_sent",
                                      "request_id": request_id or self.window.paste_request_id}) + "\n").encode()
        self.window.portal_output()

    def test_hidden_shortcut_flow_pastes_after_async_result_without_raising_window(self):
        with patch("phimthai.app.local_model", return_value=self.root / "synthetic-model"), \
             patch.object(self.window, "isActiveWindow", return_value=False), \
             patch.object(self.window, "isVisible", return_value=False), \
             patch.object(self.window, "showNormal") as show, \
             patch.object(self.window, "raise_") as raise_window:
            self.window.toggle_record()
            self.assertTrue(self.window.recording)
            self.assertEqual(self.window.feedback._phase, "listening")
            self.window.finish_recording()
            self.assertFalse(self.window.recording)
            self.assertEqual(self.window.feedback._phase, "processing")
            self.window.jobs.submit.assert_called_once()
            result = {"id": "synthetic-result", "text": "พิมพ์ไทย English",
                      "settings": asdict(self.window.record_settings)}
            QTimer.singleShot(0, lambda: self.controller.result.emit(result))
            QTest.qWait(20)
            self.assertEqual(self.window.editor.toPlainText(), result["text"])
            self.assertTrue(self.window.paste_timer.isActive())
            self.assertEqual(self.window.paste_timer.interval(), 250)
            request_id = self.window.paste_request_id
            self.assertIsNotNone(request_id)
            self.assertEqual(self.window.clipboard.offers, [result["text"]])
            self.assertEqual(self.commands, [])
            QTest.qWait(300)
            self.assertEqual(self.commands, [{"action": "paste", "request_id": request_id}])
            show.assert_not_called()
            raise_window.assert_not_called()
            self.assertEqual(self.window.feedback._phase, "processing", "Wait for the portal ACK")

    def test_manual_and_active_window_paste_keep_three_second_focus_delay(self):
        self.window.editor.setPlainText("Synthetic text only")
        for automatic, active in ((False, False), (True, True)):
            with self.subTest(automatic=automatic, active=active), \
                 patch.object(self.window, "isActiveWindow", return_value=active), \
                 patch.object(self.window, "isVisible", return_value=True), \
                 patch.object(self.window, "showMinimized") as minimize:
                self.window.paste(automatic=automatic)
                self.assertTrue(self.window.paste_timer.isActive())
                self.assertEqual(self.window.paste_timer.interval(), 3000)
                minimize.assert_called_once()
                self.window.cancel()
                self.assertFalse(self.window.paste_timer.isActive())
                self.assertFalse(self.window.paste_busy)
                self.assertEqual(self.commands, [])

    def test_acknowledgement_shows_typing_but_late_ack_cannot_revive_cancelled_feedback(self):
        self.window.editor.setPlainText("Synthetic text only")
        self.window.paste()
        self.window.paste_timer.stop()
        self.window.send_paste()
        self.acknowledge_paste()
        self.assertEqual(self.window.feedback._phase, "typing")
        self.assertEqual(self.window.clipboard.restore_requests, 1)
        self.window.clipboard.restore()

        self.window.feedback.processing()
        self.window.paste()
        self.window.paste_timer.stop()
        self.window.send_paste()
        cancelled_request = self.window.paste_request_id
        self.window.cancel()  # Sent request, but the portal has not acknowledged it yet.
        self.assertEqual(self.window.feedback._phase, "idle")
        self.assertTrue(self.window.paste_busy)
        self.assertTrue(self.window.paste_committed)
        self.assertTrue(self.window.clipboard.owns_clipboard())
        self.acknowledge_paste(cancelled_request)
        self.assertEqual(self.window.feedback._phase, "idle", "A late ACK revived cancelled feedback")
        self.assertEqual(self.window.clipboard.restore_requests, 2)
        self.assertTrue(self.window.clipboard.owns_clipboard(), "Keep the offer until delayed restore")
        self.window.clipboard.restore()
        self.assertFalse(self.window.paste_busy)
        self.assertFalse(self.window.paste_committed)

    def test_old_ack_and_error_cannot_restore_a_new_clipboard_offer(self):
        window = self.window
        window.editor.setPlainText("First synthetic paste")
        window.paste()
        first_id = window.paste_request_id
        window.paste_timer.stop()
        window.send_paste()
        window.cancel()

        window.editor.setPlainText("Second synthetic paste")
        window.paste()
        self.assertEqual(window.paste_inflight, first_id)
        self.assertEqual(window.clipboard.offers, ["First synthetic paste"],
                         "A still-running key injection must not see the next clipboard offer")
        self.assertTrue(window.clipboard.owns_clipboard(), "Cancel must not replace data while keys are in flight")
        self.acknowledge_paste(first_id)
        self.assertIsNone(window.paste_inflight)
        self.assertNotEqual(window.feedback._phase, "typing")
        self.assertEqual(window.clipboard.restore_requests, 1)
        window.paste()
        self.assertEqual(window.clipboard.offers, ["First synthetic paste"],
                         "ACK is not permission to overwrite a still-consumable clipboard offer")
        self.assertTrue(window.paste_committed)
        window.clipboard.restore()
        self.assertFalse(window.paste_committed)

        window.feedback.processing()
        window.paste()
        second_id = window.paste_request_id
        self.assertNotEqual(first_id, second_id)
        status_before = window.status.text()
        self.acknowledge_paste(first_id)
        self.responses = (json.dumps({"event": "error", "action": "paste", "request_id": first_id,
                                      "error": "Late failure from the first paste"}) + "\n").encode()
        window.portal_output()

        self.assertEqual(window.paste_request_id, second_id)
        self.assertTrue(window.paste_busy)
        self.assertTrue(window.paste_timer.isActive())
        self.assertTrue(window.clipboard.owns_clipboard())
        self.assertEqual(window.clipboard.restore_requests, 1)
        self.assertEqual(window.feedback._phase, "processing")
        self.assertEqual(window.status.text(), status_before)
        self.assertEqual(self.commands, [{"action": "paste", "request_id": first_id}])

        window.paste_timer.stop()
        window.send_paste()
        self.assertEqual(self.commands[-1], {"action": "paste", "request_id": second_id})
        self.acknowledge_paste(second_id)
        self.assertEqual(window.feedback._phase, "typing")
        self.assertEqual(window.clipboard.restore_requests, 2)

    def test_cancelled_paste_error_delays_restore_without_reviving_feedback(self):
        window = self.window
        window.editor.setPlainText("Synthetic payload kept until release")
        window.paste()
        request_id = window.paste_request_id
        window.paste_timer.stop()
        window.send_paste()
        window.cancel()
        self.responses = (json.dumps({"event": "error", "action": "paste",
                                      "request_id": request_id, "error": "Synthetic release failure"}) + "\n").encode()
        window.portal_output()
        self.assertIsNone(window.paste_inflight)
        self.assertTrue(window.paste_committed)
        self.assertTrue(window.clipboard.owns_clipboard())
        self.assertEqual(window.clipboard.restore_requests, 1)
        self.assertEqual(window.feedback._phase, "idle")
        window.clipboard.restore()
        self.assertFalse(window.paste_committed)
        self.assertFalse(window.paste_busy)

    def test_cancel_after_ack_keeps_offer_until_delayed_restore(self):
        window = self.window
        window.editor.setPlainText("Synthetic payload for a slow target")
        window.paste()
        window.paste_timer.stop()
        window.send_paste()
        self.acknowledge_paste()
        window.cancel()
        self.assertIsNone(window.paste_inflight)
        self.assertTrue(window.paste_committed)
        self.assertTrue(window.clipboard.owns_clipboard())
        self.assertEqual(window.clipboard.restore_requests, 1)
        window.clipboard.restore()
        self.assertFalse(window.paste_committed)
        self.assertFalse(window.paste_busy)


if __name__ == "__main__":
    unittest.main()
