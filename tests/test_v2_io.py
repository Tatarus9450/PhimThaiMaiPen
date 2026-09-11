"""Disk failures must preserve transcripts and stop the recording device."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from phimthai import performance, worker
from phimthai.app import MainWindow
from phimthai.audio import Recorder
from phimthai.settings import Settings, data_dir


APP = QApplication.instance() or QApplication([])


class CaptureWriteFailureTests(unittest.TestCase):
    def setUp(self):
        self.recorder = Recorder()
        self.source = Mock()
        self.output = Mock()
        self.recorder.source = self.source
        self.recorder.output = self.output
        self.recorder.device = Mock()
        self.recorder.device.readAll.return_value = b"\x01\x00\x02\x00"
        self.recorder.frame_size = 2
        self.errors = []
        self.recorder.failed.connect(self.errors.append)

    def assert_capture_closed(self):
        self.source.stop.assert_called_once_with()
        self.source.deleteLater.assert_called_once_with()
        self.output.close.assert_called_once_with()
        self.assertIsNone(self.recorder.source)
        self.assertIsNone(self.recorder.device)
        self.assertIsNone(self.recorder.output)
        self.assertFalse(self.recorder.stop())
        self.assertEqual(len(self.errors), 1)

    def test_audio_write_failure_stops_device_before_reporting_error(self):
        self.output.writeframesraw.side_effect = OSError("audio disk full")
        stopped_when_reported = []
        self.recorder.failed.connect(lambda _: stopped_when_reported.append(self.source.stop.called))
        self.recorder.read()
        self.assert_capture_closed()
        self.assertEqual(stopped_when_reported, [True])
        self.assertIn("audio disk full", self.errors[0])

    def test_final_header_write_failure_still_stops_device(self):
        self.output.close.side_effect = OSError("cannot finish WAV header")
        self.assertFalse(self.recorder.stop())
        self.assert_capture_closed()
        self.assertIn("cannot finish WAV header", self.errors[0])


class IsolatedDataTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-io-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        environment.start()
        self.addCleanup(environment.stop)


class PerformanceFailureTests(IsolatedDataTest):
    def test_measurement_write_failure_does_not_discard_successful_asr(self):
        import typhoon_service as service
        # A real filesystem error in the optional measurement write path.
        (data_dir() / "performance.tmp").mkdir(parents=True)
        transcript = {"ok": True, "text": "ถอดเสียงสำเร็จ", "device": "cpu",
                      "audio_duration": 3, "processing_time": 0.4}
        transcribe = Mock(return_value=transcript)
        with patch("phimthai.worker.local_model", return_value=self.root), \
             patch.object(service, "import_runtime_modules"), \
             patch.object(service, "TORCH", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))), \
             patch.object(service, "transcribe_audio", transcribe), \
             patch.dict(service.CONFIG, {}), contextlib.redirect_stderr(io.StringIO()) as diagnostic:
            result = worker.run_inference({"action": "transcribe", "audio": "unused.wav",
                                           "settings": asdict(Settings(device="cpu"))})
        transcribe.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "ถอดเสียงสำเร็จ")
        self.assertIn("Performance measurement could not be saved", diagnostic.getvalue())

    def test_invalid_measurement_shapes_do_not_break_automatic_device_selection(self):
        directory = data_dir()
        directory.mkdir(parents=True)
        for values in ([], "broken", {"qwen-0.6b": []},
                       {"qwen-0.6b": {"cpu": "broken", "cuda": [None, "1", -1, True]}}):
            with self.subTest(values=values):
                (directory / "performance.json").write_text(json.dumps({performance.machine_key(): values}))
                device, _ = performance.choose("qwen-0.6b", ["cpu", "cuda"], "speed")
                self.assertEqual(device, "cpu")


class TranscriptPersistenceFailureTests(IsolatedDataTest):
    def setUp(self):
        super().setUp()
        with patch.object(MainWindow, "setup_tray"), \
             patch.object(MainWindow, "refresh_diagnostics"), \
             patch("phimthai.app.QMediaDevices.audioInputs", return_value=[]), \
             patch("phimthai.app.installed_size", return_value=0):
            self.window = MainWindow()
        self.window.clipboard = Mock()
        self.window.paste = Mock()
        self.window.showNormal = Mock()
        self.window.raise_ = Mock()
        self.addCleanup(self.window.close)

    def test_setup_save_failure_preserves_text_and_immediate_paste(self):
        settings = Settings(paste_mode="immediate")
        self.window.editor.setPlainText("previous text")
        with patch("phimthai.app.save_settings", side_effect=OSError("config disk full")):
            self.window.completed({"id": "setup-error", "text": "new transcript", "settings": asdict(settings)})
        self.assertEqual(self.window.editor.toPlainText(), "new transcript")
        self.window.paste.assert_called_once_with()
        self.assertIn("config disk full", self.window.status.text())
        self.assertFalse(self.window.settings.onboarding_done)

    def test_history_directory_failure_preserves_text_and_immediate_paste(self):
        directory = data_dir()
        directory.mkdir(parents=True)
        (directory / "history").write_text("blocks creating a directory")
        self.window.settings.onboarding_done = True
        settings = Settings(keep_history=True, paste_mode="immediate")
        self.window.completed({"id": "history-error", "text": "retained transcript", "settings": asdict(settings)})
        self.assertEqual(self.window.editor.toPlainText(), "retained transcript")
        self.window.paste.assert_called_once_with()
        self.assertIn("history could not be saved", self.window.status.text())

    def test_audio_history_uses_job_opt_in_and_copies_before_temporary_cleanup(self):
        self.window.settings.onboarding_done = True
        self.window.settings.keep_audio_history = True
        source = Path(self.window.temp.name) / "sample.wav"
        source.write_bytes(b"test recording data")
        self.window.completed({"id": "private", "text": "private text", "source_audio": str(source),
                               "settings": asdict(Settings(keep_audio_history=False))})
        self.assertFalse((data_dir() / "audio-history").exists())
        source.write_bytes(b"opted-in recording data")
        self.window.settings.keep_audio_history = False
        self.window.completed({"id": "saved", "text": "saved text", "source_audio": str(source),
                               "settings": asdict(Settings(keep_audio_history=True))})
        saved = data_dir() / "audio-history/saved.wav"
        self.assertEqual(saved.read_bytes(), b"opted-in recording data")
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertFalse(source.exists())

    def test_audio_history_copy_failure_removes_partial_file_and_preserves_text(self):
        self.window.settings.onboarding_done = True
        source = self.root / "source.wav"
        source.write_bytes(b"original data")
        with patch("phimthai.app.shutil.copyfileobj", side_effect=OSError("disk full")):
            self.window.completed({"id": "failed", "text": "still available", "source_audio": str(source),
                                   "settings": asdict(Settings(keep_audio_history=True))})
        self.assertEqual(self.window.editor.toPlainText(), "still available")
        self.assertFalse((data_dir() / "audio-history/failed.wav").exists())

    def test_missing_saved_microphone_never_becomes_system_default(self):
        missing_id = b"missing-usb".hex()
        self.window.settings.microphone = missing_id
        self.window.microphone.clear()
        other = SimpleNamespace(id=lambda: b"other-input", description=lambda: "Other input")
        with patch("phimthai.app.QMediaDevices.audioInputs", return_value=[other]):
            self.window.refresh_microphones()
        self.assertEqual(self.window.current_settings().microphone, missing_id)
        item = self.window.microphone.model().item(self.window.microphone.currentIndex())
        self.assertFalse(item.isEnabled())
        with patch("phimthai.audio.QMediaDevices.audioInputs", return_value=[other]), \
             patch("phimthai.audio.QAudioSource") as audio_source:
            with self.assertRaisesRegex(RuntimeError, "disconnected"):
                self.window.recorder.start(self.root / "must-not-record.wav", missing_id)
            audio_source.assert_not_called()
        self.assertFalse((self.root / "must-not-record.wav").exists())

    def test_refresh_preserves_unsaved_microphone_selection_across_reconnect(self):
        first = SimpleNamespace(id=lambda: b"first-input", description=lambda: "First input")
        chosen = SimpleNamespace(id=lambda: b"chosen-input", description=lambda: "Chosen input")
        chosen_id = b"chosen-input".hex()
        with patch("phimthai.app.QMediaDevices.audioInputs", return_value=[first, chosen]):
            self.window.refresh_microphones()
        self.window.microphone.setCurrentIndex(self.window.microphone.findData(chosen_id))
        with patch("phimthai.app.QMediaDevices.audioInputs", return_value=[first]):
            self.window.refresh_microphones()
        self.assertEqual(self.window.current_settings().microphone, chosen_id)
        self.assertFalse(self.window.microphone.model().item(self.window.microphone.currentIndex()).isEnabled())
        with patch("phimthai.app.QMediaDevices.audioInputs", return_value=[first, chosen]):
            self.window.refresh_microphones()
        self.assertEqual(self.window.current_settings().microphone, chosen_id)
        self.assertTrue(self.window.microphone.model().item(self.window.microphone.currentIndex()).isEnabled())


if __name__ == "__main__":
    unittest.main()
