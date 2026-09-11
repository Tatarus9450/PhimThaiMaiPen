"""Pulse observer failures must never turn an interrupted take into valid audio.

The Qt objects/signals are real. Every pactl process, source list and audio
device is simulated; these tests never contact an audio server or microphone.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication

from phimthai import audio, pulse_guard


APP = QApplication.instance() or QApplication([])
SELECTED = {"name": "test-selected-mic", "index": 71}
OTHER = {"name": "test-other-mic", "index": 72}


class FakeProcess(QObject):
    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    finished = Signal(int, int)
    errorOccurred = Signal(object)
    ProcessState = QProcess.ProcessState
    instances = []
    start_success = True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stdout = b""
        self.running = False
        self.killed = False
        self.arguments = None
        self.instances.append(self)

    def setProcessEnvironment(self, environment):
        self.environment = environment

    def start(self, program, arguments):
        self.arguments = (program, arguments)
        self.running = self.start_success

    def state(self):
        return self.ProcessState.Running if self.running else self.ProcessState.NotRunning

    def waitForStarted(self, timeout):
        return self.start_success

    def waitForFinished(self, timeout):
        return not self.running

    def readAllStandardOutput(self):
        result, self.stdout = self.stdout, b""
        return result

    def readAllStandardError(self):
        return b""

    def feed(self, data):
        self.stdout += data
        self.readyReadStandardOutput.emit()

    def exit(self):
        self.running = False
        self.finished.emit(1, 0)

    def kill(self):
        self.killed = True
        self.running = False
        self.finished.emit(0, 0)


class PulseHarness(unittest.TestCase):
    def setUp(self):
        FakeProcess.instances = []
        FakeProcess.start_success = True
        self.server_sources = [dict(SELECTED), dict(OTHER)]
        process_patch = patch.object(pulse_guard, "QProcess", FakeProcess)
        process_patch.start()
        self.addCleanup(process_patch.stop)
        which_patch = patch.object(pulse_guard.shutil, "which", return_value="/usr/bin/pactl")
        self.which = which_patch.start()
        self.addCleanup(which_patch.stop)
        query_patch = patch.object(pulse_guard.subprocess, "run", side_effect=self.query)
        self.query_mock = query_patch.start()
        self.addCleanup(query_patch.stop)

    def query(self, *_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.server_sources))

    def new_guard(self):
        guard = pulse_guard.PulseSourceGuard()
        self.addCleanup(lambda: guard.stop(verify=False))
        self.errors = []
        guard.failed.connect(self.errors.append)
        guard.start(SELECTED["name"].encode())
        return guard


class PulseGuardTests(PulseHarness):
    def test_missing_selected_source_rejects_before_spawning_observer(self):
        self.server_sources = [dict(OTHER)]
        guard = pulse_guard.PulseSourceGuard()
        with self.assertRaisesRegex(RuntimeError, "microphone"):
            guard.start(SELECTED["name"].encode())
        self.assertEqual(FakeProcess.instances, [])

    def test_partial_lines_only_abort_for_the_selected_source(self):
        guard = self.new_guard()
        process = guard.process
        process.feed(b"Event 'remove' on source #72\nEvent 'remove' on source-output #71\n")
        process.feed(b"Event 'change' on source #71\nEvent 'remove' on source #7")
        self.assertEqual(self.errors, [])
        process.feed(b"1\r\n")
        self.assertEqual(len(self.errors), 1)
        self.assertIn("discard", self.errors[0].lower())

    def test_observer_exit_reports_failure(self):
        guard = self.new_guard()
        guard.process.exit()
        self.assertEqual(len(self.errors), 1)
        self.assertIn("monitor", self.errors[0].lower())

    def test_observer_error_reports_failure(self):
        guard = self.new_guard()
        guard.process.errorOccurred.emit(QProcess.ProcessError.ReadError)
        self.assertEqual(len(self.errors), 1)

    def test_failed_process_start_cleans_up(self):
        FakeProcess.start_success = False
        guard = pulse_guard.PulseSourceGuard()
        with self.assertRaises(RuntimeError):
            guard.start(SELECTED["name"].encode())
        self.assertIsNone(guard.process)
        self.assertIsNone(guard.identity)
        self.assertTrue(FakeProcess.instances[-1].killed)

    def test_final_snapshot_rejects_recreated_source_with_same_name(self):
        guard = self.new_guard()
        process = guard.process
        self.server_sources[0]["index"] = 99
        self.assertIsNotNone(guard.stop())
        self.assertTrue(process.killed)
        self.assertEqual(self.errors, [])  # Intentional shutdown must stay quiet.

    def test_final_snapshot_query_timeout_returns_error(self):
        guard = self.new_guard()
        self.query_mock.side_effect = subprocess.TimeoutExpired("pactl", 2)
        self.assertIsNotNone(guard.stop())

    def test_dead_observer_is_rejected_even_before_exit_signal_dispatch(self):
        guard = self.new_guard()
        # QProcess can already be NotRunning before its queued signal is handled.
        guard.process.running = False
        self.assertIsNotNone(guard.stop())

    def test_old_process_events_do_not_invalidate_a_new_recording(self):
        guard = self.new_guard()
        previous = guard.process
        self.assertIsNone(guard.stop())
        guard.start(SELECTED["name"].encode())
        current = guard.process
        previous.feed(b"Event 'remove' on source #71\n")
        previous.exit()
        self.assertEqual(self.errors, [])
        self.assertIs(guard.process, current)
        current.feed(b"Event 'remove' on source #71\n")
        self.assertEqual(len(self.errors), 1)

    def test_unavailable_pactl_keeps_sandbox_qt_fallback(self):
        self.which.return_value = None
        guard = pulse_guard.PulseSourceGuard()
        with patch.object(pulse_guard.Path, "is_file", return_value=True):
            guard.start(b"sandbox-device")
        self.assertIsNone(guard.stop())
        self.query_mock.assert_not_called()
        self.assertEqual(FakeProcess.instances, [])

    def test_missing_native_observer_rejects_capture(self):
        self.which.return_value = None
        guard = pulse_guard.PulseSourceGuard()
        with patch.object(pulse_guard.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Install pactl"):
                guard.start(b"native-device")
        self.query_mock.assert_not_called()
        self.assertEqual(FakeProcess.instances, [])

    def test_invalid_server_responses_fail_closed(self):
        for code, text in [(1, "[]"), (0, "{broken"), (0, "null"), (0, "{}")]:
            with self.subTest(code=code, response=text):
                self.query_mock.side_effect = None
                self.query_mock.return_value = SimpleNamespace(returncode=code, stdout=text)
                with self.assertRaises(RuntimeError):
                    pulse_guard.PulseSourceGuard.sources()


class FakeInputDevice:
    def id(self):
        return SELECTED["name"].encode()

    def isFormatSupported(self, _format):
        return True


class FakeMediaDevices(QObject):
    audioInputsChanged = Signal()

    @staticmethod
    def audioInputs():
        return [FakeInputDevice()]

    @staticmethod
    def defaultAudioInput():
        return FakeInputDevice()


class FakeReader(QObject):
    readyRead = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = b"\x01\x00\x02\x00"

    def readAll(self):
        data, self.data = self.data, b""
        return data


class FakeAudioSource(QObject):
    stateChanged = Signal()
    instances = []

    def __init__(self, _device, _format, parent=None):
        super().__init__(parent)
        self.reader = FakeReader(self)
        self.stopped = False
        self.instances.append(self)

    def start(self):
        return self.reader

    def stop(self):
        self.stopped = True


class RecorderGuardTests(PulseHarness):
    def setUp(self):
        super().setUp()
        FakeAudioSource.instances = []
        media_patch = patch.object(audio, "QMediaDevices", FakeMediaDevices)
        media_patch.start()
        self.addCleanup(media_patch.stop)
        source_patch = patch.object(audio, "QAudioSource", FakeAudioSource)
        source_patch.start()
        self.addCleanup(source_patch.stop)
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-guard-test-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "take.wav"
        self.recorder = audio.Recorder()
        self.addCleanup(self.recorder._finish_capture)
        self.errors = []
        self.recorder.failed.connect(self.errors.append)

    def start_recording(self):
        self.recorder.start(self.path)
        self.recorder.read()
        self.assertEqual(self.recorder.frames, 2)

    def assert_recording_invalid(self, source, process):
        self.assertTrue(self.recorder.capture_failed)
        self.assertTrue(source.stopped)
        self.assertTrue(process.killed)
        self.assertIsNone(self.recorder.pulse_guard)
        self.assertIsNone(self.recorder.output)
        self.assertFalse(self.recorder.stop())

    def test_selected_removal_stops_and_invalidates_existing_audio(self):
        self.start_recording()
        source, process = self.recorder.source, self.recorder.pulse_guard.process
        process.feed(b"Event 'remove' on source #71\n")
        self.assert_recording_invalid(source, process)
        self.assertEqual(len(self.errors), 1)

    def test_observer_exit_stops_and_invalidates_existing_audio(self):
        self.start_recording()
        source, process = self.recorder.source, self.recorder.pulse_guard.process
        process.exit()
        self.assert_recording_invalid(source, process)
        self.assertEqual(len(self.errors), 1)

    def test_final_snapshot_catches_unplug_missed_by_startup_subscription(self):
        self.start_recording()
        source, process = self.recorder.source, self.recorder.pulse_guard.process
        self.server_sources = [dict(OTHER)]
        self.assertFalse(self.recorder.stop())
        self.assert_recording_invalid(source, process)
        self.assertEqual(len(self.errors), 1)

    def test_previous_guard_signal_cannot_stop_new_take(self):
        self.start_recording()
        previous = self.recorder.pulse_guard
        self.assertTrue(self.recorder.stop())
        self.start_recording()
        source, current = self.recorder.source, self.recorder.pulse_guard
        previous.failed.emit("late failure from old take")
        self.assertIs(self.recorder.pulse_guard, current)
        self.assertFalse(source.stopped)
        self.assertFalse(self.recorder.capture_failed)
        self.assertEqual(self.errors, [])
        self.assertTrue(self.recorder.stop())

    def test_output_creation_failure_reaps_already_started_observer(self):
        with patch.object(audio.wave, "open", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.recorder.start(self.path)
        self.assertIsNone(self.recorder.pulse_guard)
        self.assertTrue(self.recorder.capture_failed)
        self.assertTrue(FakeProcess.instances[-1].killed)
        self.assertEqual(FakeAudioSource.instances, [])


if __name__ == "__main__":
    unittest.main()
