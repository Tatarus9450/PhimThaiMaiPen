"""Review regressions using isolated settings, offscreen Qt and fake portals."""
import asyncio
import json
import os
import queue
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from phimthai import portals
from phimthai.app import MainWindow
from phimthai.settings import Settings


APP = QApplication.instance() or QApplication([])


class IsolatedWindow:
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-app-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        # Do not enumerate real microphones, open a tray or inspect model caches.
        with patch.object(MainWindow, "setup_tray"), \
             patch.object(MainWindow, "refresh_diagnostics"), \
             patch.object(MainWindow, "refresh_device_choices"), \
             patch("phimthai.app.QMediaDevices.audioInputs", return_value=[]), \
             patch("phimthai.app.installed_size", return_value=0):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.window.clipboard = Mock()
        self.window.clipboard.owns_clipboard.return_value = True
        self.controller = self.window.jobs
        self.window.jobs = Mock(busy=False)

    def audio(self, name):
        path = Path(self.window.temp.name) / name
        path.write_bytes(b"isolated recording fixture; no real microphone")
        return path


class RetryAndSilenceTests(IsolatedWindow, unittest.TestCase):
    def test_retry_uses_new_audio_after_model_download_blocks_submission(self):
        previous, latest = self.audio("previous.wav"), self.audio("latest.wav")
        settings = Settings()
        self.window.last_request = (previous, settings)
        self.window.audio_path = latest
        self.window.downloading_model = settings.model
        self.window.transcribe(latest, settings)
        self.window.jobs.submit.assert_not_called()

        self.window.downloading_model = None
        self.window.retry()
        self.assertEqual(self.window.jobs.submit.call_args.kwargs["audio"], str(latest))
        self.assertEqual(self.window.last_request[0], latest)

    def test_no_speech_prunes_older_audio_and_keeps_latest_for_retry(self):
        settings = Settings()
        first = self.audio("first-silent.wav")
        self.window.last_request = (first, settings)
        self.window.completed({"id": "first", "no_speech": True, "settings": asdict(settings)})
        latest = self.audio("latest-silent.wav")
        self.window.last_request = (latest, settings)
        self.window.completed({"id": "latest", "no_speech": True, "settings": asdict(settings)})
        self.assertFalse(first.exists(), "Earlier silent recordings must not accumulate")
        self.assertTrue(latest.exists(), "Keep only the latest recording for Retry")

    def test_failed_jobs_prune_older_audio_and_keep_latest_for_retry(self):
        settings = Settings()
        first = self.audio("first-failed.wav")
        self.window.transcribe(first, settings)
        self.controller.failed.emit("Model unavailable")
        latest = self.audio("latest-failed.wav")
        self.window.transcribe(latest, settings)
        self.controller.failed.emit("Worker stopped unexpectedly")
        self.assertFalse(first.exists(), "Earlier failed recordings must not accumulate")
        self.assertTrue(latest.exists(), "Keep only the latest recording for Retry")


class QueuedPasteTests(IsolatedWindow, unittest.IsolatedAsyncioTestCase):
    async def test_saving_opt_out_during_grant_cannot_recreate_restore_token(self):
        requests = queue.Queue()
        entered, release = asyncio.Event(), asyncio.Event()

        async def permission_dialog(persist=False):
            entered.set()
            await release.wait()
            if persist:
                portals.remember(paste_token="isolated-test-restore-token")

        client = SimpleNamespace(connect=AsyncMock(), enable_paste=permission_dialog)
        self.window.portal = SimpleNamespace(write=lambda raw: requests.put(raw.decode()))
        self.addCleanup(setattr, self.window, "portal", None)
        self.window.remember_desktop.setChecked(True)
        with patch.object(portals, "Portals", return_value=client), \
             patch.object(portals, "emit"), \
             patch.object(portals.sys, "stdin", SimpleNamespace(readline=requests.get)):
            loop = asyncio.create_task(portals.main())
            try:
                self.window.portal_command("enable_paste", persist=True)
                await asyncio.wait_for(entered.wait(), timeout=2)
                self.window.remember_desktop.setChecked(False)
                self.window.save()
            finally:
                release.set()
                requests.put("")
                await asyncio.wait_for(loop, timeout=2)
        self.assertFalse(self.window.settings.remember_desktop)
        self.assertEqual(portals.saved_state(), {})

    async def test_cancel_suppresses_paste_queued_behind_permission_dialog(self):
        # Exercise the actual UI commands and portal command loop. Only the
        # desktop permission operation and stdin transport are replaced.
        requests = queue.Queue()
        entered, release = asyncio.Event(), asyncio.Event()

        async def permission_dialog(*args, **kwargs):
            entered.set()
            await release.wait()

        client = SimpleNamespace(
            connect=AsyncMock(), enable_shortcuts=permission_dialog,
            paste=AsyncMock(),
        )
        self.window.portal = SimpleNamespace(write=lambda raw: requests.put(raw.decode()))
        self.addCleanup(setattr, self.window, "portal", None)
        self.window.paste_enabled = True
        self.window.editor.setPlainText("Cancelled text must not cause a later Ctrl+V")
        with patch.object(portals, "Portals", return_value=client), \
             patch.object(portals, "emit"), \
             patch.object(portals.sys, "stdin", SimpleNamespace(readline=requests.get)):
            loop = asyncio.create_task(portals.main())
            try:
                self.window.portal_command("shortcuts", trigger="CTRL+ALT+SPACE")
                await asyncio.wait_for(entered.wait(), timeout=2)
                self.window.paste()
                if self.window.paste_timer.isActive():
                    self.window.paste_timer.stop()
                    self.window.send_paste()  # The visible 3-second countdown ended.
                self.window.cancel()  # Permission dialog is still pending.
            finally:
                release.set()
                requests.put("")
                await asyncio.wait_for(loop, timeout=2)
        client.paste.assert_not_awaited()


class PermissionGateTests(IsolatedWindow, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.commands = []
        self.bridge = SimpleNamespace(
            write=lambda raw: self.commands.append(json.loads(raw)),
        )
        self.window.portal = self.bridge
        self.addCleanup(setattr, self.window, "portal", None)
        self.window.paste_enabled = True
        self.window.editor.setPlainText("controlled clipboard offer")

    def test_permission_request_cancels_countdown_and_blocks_overlap_until_finished(self):
        self.window.paste()
        self.assertTrue(self.window.paste_timer.isActive())
        self.window.portal_command("shortcuts", trigger="CTRL+ALT+SPACE")
        self.assertFalse(self.window.paste_timer.isActive())
        self.assertFalse(self.window.paste_busy)
        self.window.clipboard.restore.assert_called()
        self.window.portal_command("enable_paste")
        self.window.paste()
        self.assertEqual([item["action"] for item in self.commands], ["shortcuts"])
        self.assertEqual(self.window.clipboard.offer.call_count, 1)

        self.bridge.readAllStandardOutput = lambda: b'{"event":"command_finished","action":"shortcuts"}\n'
        self.window.portal_output()
        self.window.paste()
        self.assertTrue(self.window.paste_timer.isActive())
        self.assertEqual(self.window.clipboard.offer.call_count, 2)

    def test_sent_paste_finishes_before_permission_configuration_can_start(self):
        self.window.paste()
        self.window.paste_timer.stop()
        self.window.send_paste()
        self.window.portal_command("shortcuts", trigger="CTRL+ALT+SPACE")
        self.assertEqual([item["action"] for item in self.commands], ["paste"])
        self.assertFalse(self.window.portal_permission_pending)

    def test_bridge_exit_releases_permission_gate_and_disables_paste(self):
        self.window.portal_command("enable_paste")
        self.assertTrue(self.window.portal_permission_pending)
        self.window.portal_finished()
        self.assertFalse(self.window.portal_permission_pending)
        self.assertFalse(self.window.paste_enabled)
        self.window.clipboard.restore.assert_called()


if __name__ == "__main__":
    unittest.main()
