import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication

from phimthai.clipboard import ClipboardTransaction
from phimthai.jobs import JobController
from phimthai.settings import Settings, load_settings, save_settings

APP = QApplication.instance() or QApplication([])


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    if not predicate():
        raise AssertionError("Timed out waiting for event")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.jobs = JobController(worker_module="tests.echo_worker")
        self.results, self.errors = [], []
        self.jobs.result.connect(self.results.append)
        self.jobs.failed.connect(self.errors.append)

    def tearDown(self):
        self.jobs.cancel()

    def test_100_sequential_jobs_keep_identity_and_one_worker(self):
        expected = []
        for i in range(100):
            expected.append(self.jobs.submit(Settings(), action="transcribe", text=f"งาน {i}"))
            until(lambda: len(self.results) == i + 1)
        self.assertEqual([r["id"] for r in self.results], expected)
        self.assertEqual([r["text"] for r in self.results], [f"งาน {i}" for i in range(100)])
        self.assertEqual(len({r["pid"] for r in self.results}), 1)
        self.assertEqual(self.errors, [])

    def test_cancel_drops_active_and_queued_results(self):
        self.jobs.submit(Settings(), action="transcribe", text="cancelled", delay=5)
        self.jobs.submit(Settings(), action="transcribe", text="queued")
        until(lambda: self.jobs.process is not None)
        self.jobs.cancel()
        fresh = self.jobs.submit(Settings(), action="transcribe", text="fresh")
        until(lambda: len(self.results) == 1)
        self.assertEqual(self.results[0]["id"], fresh)
        self.assertEqual(self.results[0]["text"], "fresh")

    def test_worker_crash_recovery(self):
        self.jobs.submit(Settings(), action="transcribe", crash=True)
        until(lambda: bool(self.errors))
        self.jobs.submit(Settings(), action="transcribe", text="recovered")
        until(lambda: bool(self.results))
        self.assertEqual(self.results[0]["text"], "recovered")

    def test_model_change_restarts_worker(self):
        self.jobs.submit(Settings(), action="transcribe")
        until(lambda: len(self.results) == 1)
        self.jobs.submit(replace(Settings(), model="qwen-1.7b"), action="transcribe")
        until(lambda: len(self.results) == 2)
        self.assertNotEqual(self.results[0]["pid"], self.results[1]["pid"])


class ClipboardTests(unittest.TestCase):
    def tearDown(self):
        APP.clipboard().clear()

    def test_restores_all_mime_formats(self):
        data = QMimeData()
        data.setText("original")
        data.setData("application/test-binary", b"\x00\xff\x01")
        APP.clipboard().setMimeData(data)
        transaction = ClipboardTransaction()
        transaction.offer("สวัสดี hello")
        self.assertEqual(APP.clipboard().text(), "สวัสดี hello")
        transaction.restore()
        self.assertEqual(APP.clipboard().text(), "original")
        self.assertEqual(bytes(APP.clipboard().mimeData().data("application/test-binary")), b"\x00\xff\x01")

    def test_never_overwrites_new_user_copy(self):
        APP.clipboard().setText("original")
        transaction = ClipboardTransaction()
        transaction.offer("transcript")
        APP.clipboard().setText("new user copy")
        transaction.restore()
        self.assertEqual(APP.clipboard().text(), "new user copy")


class SettingsAndTranslationTests(unittest.TestCase):
    def test_settings_roundtrip_and_invalid_value(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_CONFIG_HOME": directory}):
            save_settings(Settings(dictionary="ชื่อ\tName"))
            self.assertEqual(load_settings().dictionary, "ชื่อ\tName")
            with self.assertRaises(ValueError):
                save_settings(Settings(device="unknown"))
            self.assertEqual(load_settings().device, "auto")

    def test_long_translation_keeps_every_character(self):
        import typhoon_service as service
        # A tokenizer with one token per character forces multiple chunks;
        # identity translation independently checks loss/duplication at splits.
        tokenizer = Mock()
        tokenizer.encode.side_effect = lambda text: list(text) + [0, 1]
        source = "ภาษาไทยไม่มีช่องว่าง" * 100
        chunks = []
        def translate(text):
            chunks.append(text)
            return text
        with patch.object(service, "TRANSLATION_TOKENIZER", tokenizer), patch.object(service, "_translate_chunk_loaded", side_effect=translate):
            result = service._translate_text_loaded(source)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(tokenizer.encode(chunk)) <= 480 for chunk in chunks))
        self.assertEqual("".join(chunks), source)
        self.assertEqual(result.replace(" ", ""), source)


if __name__ == "__main__":
    unittest.main()
