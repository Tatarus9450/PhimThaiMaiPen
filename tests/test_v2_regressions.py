"""Regression checks for model integrity, job consent, and cancelled side effects."""
import hashlib
import json
import os
import tempfile
import textwrap
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch

# Never connect these tests to a user's desktop clipboard or recording devices.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from phimthai.app import MainWindow
from phimthai.jobs import JobController
from phimthai.models import CATALOG, local_model, model_dir
from phimthai.settings import Settings, data_dir


APP = QApplication.instance() or QApplication([])


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        APP.processEvents()
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for the regression fixture")


def pump_for(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)


class IsolatedSettingsTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phimthai-regression-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
        })
        environment.start()
        self.addCleanup(environment.stop)


class ModelIntegrityRegressionTests(IsolatedSettingsTest):
    def setUp(self):
        super().setUp()
        self.model_id = "qwen-1.7b"
        self.directory = model_dir(self.model_id)
        self.directory.mkdir(parents=True)
        self.manifest = self.directory / "verified.json"

    def test_invalid_or_empty_manifest_is_unavailable_without_raising(self):
        invalid = ["{broken", "[]", "null", json.dumps({
            "version": 2, "revision": CATALOG[self.model_id].revision, "files": {},
        })]
        for value in invalid:
            with self.subTest(manifest=value):
                self.manifest.write_text(value)
                self.assertIsNone(local_model(self.model_id))
                self.assertIsNone(local_model(self.model_id, verify=True))

    def test_same_size_corruption_invalidates_previously_verified_model(self):
        contents = {"config.json": b"{}", "tokenizer_config.json": b"{}",
                    "model.safetensors": b"original weights"}
        metadata = {}
        for name, content in contents.items():
            (self.directory / name).write_bytes(content)
            metadata[name] = {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        self.manifest.write_text(json.dumps({"version": 2,
            "revision": CATALOG[self.model_id].revision, "files": metadata}))
        self.assertEqual(local_model(self.model_id, verify=True), self.directory)

        weights = self.directory / "model.safetensors"
        original_stat = weights.stat()
        weights.write_bytes(b"corrupted weight")
        self.assertEqual(weights.stat().st_size, original_stat.st_size)
        self.assertIsNone(local_model(self.model_id, verify=True))


class JobSettingsRegressionTests(IsolatedSettingsTest):
    def setUp(self):
        super().setUp()
        self.jobs = JobController(worker_module="tests.echo_worker", temp_root=self.root)
        self.addCleanup(self.jobs.cancel)
        self.results, self.errors = [], []
        self.jobs.result.connect(self.results.append)
        self.jobs.failed.connect(self.errors.append)

    def test_job_keeps_submitted_settings_and_ui_preferences_reuse_worker(self):
        settings = Settings(keep_history=False, paste_mode="review")
        first = self.jobs.submit(settings, action="transcribe", text="first", delay=0.05)
        settings.keep_history = True
        settings.paste_mode = "immediate"
        settings.hotkey = "CTRL+ALT+T"
        second = self.jobs.submit(settings, action="transcribe", text="second")
        until(lambda: len(self.results) == 2)
        self.assertEqual(self.errors, [])
        self.assertEqual([result["id"] for result in self.results], [first, second])
        self.assertFalse(self.results[0]["settings"]["keep_history"])
        self.assertEqual(self.results[0]["settings"]["paste_mode"], "review")
        self.assertTrue(self.results[1]["settings"]["keep_history"])
        self.assertEqual(self.results[1]["settings"]["paste_mode"], "immediate")
        self.assertEqual(self.results[0]["pid"], self.results[1]["pid"])

    def test_idle_release_frees_worker_and_next_job_still_completes(self):
        self.jobs.submit(Settings(), action="transcribe", text="before idle")
        until(lambda: len(self.results) == 1 and self.jobs.idle_timer.isActive())
        old_directory = Path(self.jobs.worker_temp.name)
        self.jobs.idle_timer.timeout.emit()
        self.assertIsNone(self.jobs.process)
        self.assertFalse(old_directory.exists())
        self.jobs.submit(Settings(), action="transcribe", text="after idle")
        until(lambda: len(self.results) == 2)
        self.assertEqual([item["text"] for item in self.results], ["before idle", "after idle"])
        self.assertEqual(self.errors, [])

    def test_cancel_kills_descendant_and_removes_its_private_audio(self):
        report = self.root / "child-ready.json"
        child_code = textwrap.dedent("""
            import json, os, sys, tempfile, time
            from pathlib import Path
            with tempfile.NamedTemporaryFile(prefix='voice_agent_', suffix='.wav', delete=False) as audio:
                audio.write(b'synthetic audio fixture')
                artifact = audio.name
            report = Path(sys.argv[1])
            pending = report.with_suffix('.tmp')
            pending.write_text(json.dumps({'pid': os.getpid(), 'artifact': artifact}))
            pending.replace(report)
            time.sleep(60)
        """)
        module = self.root / "phimthai_regression_child.py"
        module.write_text(textwrap.dedent(f"""
            import json, subprocess, sys, time
            print(json.dumps({{'event': 'ready'}}), flush=True)
            request = json.loads(sys.stdin.readline())
            subprocess.Popen([sys.executable, '-c', {child_code!r}, request['report']])
            time.sleep(60)
        """))
        self.jobs.worker_module = module.stem
        pythonpath = os.pathsep.join(filter(None, [str(self.root), os.environ.get("PYTHONPATH", "")]))
        with patch.dict(os.environ, {"PYTHONPATH": pythonpath}):
            self.jobs.submit(Settings(), action="transcribe", report=str(report))
        until(report.exists)
        child = json.loads(report.read_text())
        artifact = Path(child["artifact"])
        worker_directory = artifact.parent
        self.assertTrue(artifact.exists())
        self.assertTrue(artifact.is_relative_to(self.root))
        self.assertEqual(worker_directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(os.getpgid(child["pid"]), self.jobs.worker_pid)

        self.jobs.cancel()
        self.assertFalse(artifact.exists())
        self.assertFalse(worker_directory.exists())
        self.assertFalse(self.jobs.busy)

        def child_stopped():
            try:
                # An orphan can briefly remain a zombie until init reaps it.
                return Path(f"/proc/{child['pid']}/stat").read_text().split(") ", 1)[1][0] == "Z"
            except (FileNotFoundError, ProcessLookupError):
                return True

        until(child_stopped)
        self.assertEqual(self.results, [])


class WindowSideEffectRegressionTests(IsolatedSettingsTest):
    def setUp(self):
        super().setUp()
        # No native tray, model cache lookup, or audio enumeration is needed here.
        with patch.object(MainWindow, "setup_tray"), \
             patch("phimthai.app.QMediaDevices.audioInputs", return_value=[]), \
             patch("phimthai.app.installed_size", return_value=0):
            self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.window.clipboard = Mock()
        self.window.clipboard.owns_clipboard.return_value = True
        self.window.portal_command = Mock()

    def test_completion_uses_job_history_and_paste_consent(self):
        original = Settings(keep_history=False, paste_mode="review")
        self.window.settings = replace(original, keep_history=True, paste_mode="immediate")
        self.window.paste = Mock()
        self.window.completed({"id": "private-job", "text": "private text", "settings": asdict(original)})
        self.assertFalse((data_dir() / "history/private-job.txt").exists())
        self.window.paste.assert_not_called()

        opted_in = replace(original, keep_history=True, paste_mode="immediate")
        self.window.settings = original
        self.window.completed({"id": "saved-job", "text": "saved text", "settings": asdict(opted_in)})
        history = data_dir() / "history/saved-job.txt"
        self.assertEqual(history.read_text(), "saved text")
        self.assertEqual(history.stat().st_mode & 0o777, 0o600)
        self.window.paste.assert_called_once_with(automatic=True)

    def test_cancel_prevents_delayed_paste_and_restores_offer(self):
        self.window.editor.setPlainText("do not insert this")
        self.window.paste_enabled = True
        self.window.paste()
        self.window.clipboard.offer.assert_called_once_with("do not insert this")
        self.assertTrue(self.window.paste_timer.isActive())
        self.window.paste_timer.start(20)
        self.window.cancel()
        pump_for(0.1)
        self.assertFalse(self.window.paste_timer.isActive())
        self.window.clipboard.restore.assert_called()
        self.window.portal_command.assert_not_called()

        # Positive control: the same timer sends a new, uncancelled request.
        self.window.paste()
        self.window.paste_timer.start(20)
        until(lambda: self.window.portal_command.called)
        self.window.portal_command.assert_called_once_with("paste")


if __name__ == "__main__":
    unittest.main()
