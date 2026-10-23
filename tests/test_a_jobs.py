"""Persistent worker, idle release, prewarm, timeout scaling and stderr logging."""
import json
import logging
import os
import tempfile
import textwrap
import time
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from phimthai.jobs import JobController, audio_seconds, job_timeout_ms
from phimthai.settings import Settings

APP = QApplication.instance() or QApplication([])

FAKE_WORKER = textwrap.dedent("""
    import json, os, sys, time
    log = open(os.environ["FAKE_WORKER_LOG"], "a")
    print("fake worker booting", file=sys.stderr, flush=True)
    print(json.dumps({"event": "ready"}), flush=True)
    for line in sys.stdin:
        request = json.loads(line)
        log.write(json.dumps({"action": request.get("action"), "id": request["id"], "pid": os.getpid()}) + "\\n")
        log.flush()
        if request.get("action") == "warmup":
            time.sleep(float(os.environ.get("FAKE_WARMUP_DELAY", "0")))
            ok = os.environ.get("FAKE_WARMUP_FAIL") != "1"
            print(json.dumps({"id": request["id"], "ok": ok, "warmup": True, "error": "" if ok else "load failed"}), flush=True)
            continue
        time.sleep(request.get("delay", 0))
        print(json.dumps({"id": request["id"], "ok": True, "text": request.get("text", ""),
                          "device": "cpu", "pid": os.getpid()}), flush=True)
""")


def until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.005)
    if not predicate():
        raise AssertionError("Timed out waiting for event")


def write_wav(path, seconds, rate=16000):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\0\0" * int(rate * seconds))


class PersistentWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "phimthai_a_fake_worker.py").write_text(FAKE_WORKER)
        self.log = self.root / "requests.jsonl"
        environment = {"FAKE_WORKER_LOG": str(self.log),
                       "PYTHONPATH": os.pathsep.join(filter(None, [str(self.root), os.environ.get("PYTHONPATH", "")]))}
        patcher = patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.jobs = JobController(worker_module="phimthai_a_fake_worker", temp_root=self.temp.name)
        self.addCleanup(self.jobs.cancel)
        self.results, self.errors, self.warm = [], [], []
        self.jobs.result.connect(self.results.append)
        self.jobs.failed.connect(self.errors.append)
        self.jobs.warm_changed.connect(self.warm.append)

    def requests(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_worker_persists_between_jobs_and_idle_timer_releases(self):
        self.jobs.idle_timeout_ms = 400
        self.jobs.submit(Settings(), action="transcribe", text="one")
        until(lambda: len(self.results) == 1)
        until(lambda: self.jobs.idle_timer.isActive())
        self.assertIsNotNone(self.jobs.process)
        self.assertTrue(self.jobs.warm)
        self.assertTrue(self.jobs.ready_model)
        self.jobs.submit(Settings(), action="transcribe", text="two")
        until(lambda: len(self.results) == 2)
        self.assertEqual(self.results[0]["pid"], self.results[1]["pid"])
        pid = self.results[0]["pid"]
        until(lambda: self.jobs.process is None, timeout=5)
        self.assertFalse(Path(f"/proc/{pid}").exists() and
                         Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z")
        self.assertIsNone(self.jobs.worker_temp)
        self.assertFalse(self.jobs.warm)
        self.assertEqual(self.warm, [True, False])
        self.assertEqual(self.errors, [])

    def test_idle_timer_restarts_after_each_job(self):
        self.jobs.idle_timeout_ms = 300
        for index in range(3):
            self.jobs.submit(Settings(), action="transcribe", text=str(index))
            until(lambda: len(self.results) == index + 1)
            APP.processEvents()
            time.sleep(0.2)
            APP.processEvents()
            self.assertIsNotNone(self.jobs.process)
        self.assertEqual(len({r["pid"] for r in self.results}), 1)

    def test_cancel_stops_worker_immediately(self):
        self.jobs.submit(Settings(), action="transcribe", text="one")
        until(lambda: len(self.results) == 1)
        self.jobs.cancel()
        self.assertIsNone(self.jobs.process)
        self.assertFalse(self.jobs.idle_timer.isActive())

    def test_prewarm_is_not_busy_and_emits_nothing(self):
        os.environ["FAKE_WARMUP_DELAY"] = "0.3"
        statuses = []
        self.jobs.changed.connect(statuses.append)
        self.assertIsNotNone(self.jobs.prewarm(Settings()))
        self.assertFalse(self.jobs.busy)
        self.assertTrue(self.jobs.warming)
        self.assertFalse(self.jobs.warm)
        until(lambda: self.warm == [True])
        self.assertFalse(self.jobs.busy)
        self.assertEqual((self.results, self.errors, statuses), ([], [], []))
        self.assertEqual([r["action"] for r in self.requests()], ["warmup"])
        # Already warm for this signature: no second warmup.
        self.assertIsNone(self.jobs.prewarm(Settings()))
        until(self.jobs.idle_timer.isActive)

    def test_job_submitted_during_warmup_dispatches_once_after_it(self):
        os.environ["FAKE_WARMUP_DELAY"] = "0.3"
        self.jobs.prewarm(Settings())
        until(lambda: self.requests())
        job = self.jobs.submit(Settings(), action="transcribe", text="spoken")
        self.assertTrue(self.jobs.busy)
        until(lambda: len(self.results) == 1)
        APP.processEvents()
        time.sleep(0.1)
        APP.processEvents()
        self.assertEqual(self.results[0]["id"], job)
        requests = self.requests()
        self.assertEqual([r["action"] for r in requests], ["warmup", "transcribe"])
        self.assertEqual(len({r["pid"] for r in requests}), 1)
        self.assertFalse(self.jobs.busy)

    def test_warmup_failure_is_logged_not_emitted(self):
        os.environ["FAKE_WARMUP_FAIL"] = "1"
        with self.assertLogs("phimthai.worker", logging.INFO) as logs:
            self.jobs.prewarm(Settings())
            until(lambda: not self.jobs.warming)
            until(lambda: any("warmup failed" in line for line in logs.output))
        self.assertEqual((self.results, self.errors), ([], []))
        self.assertFalse(self.jobs.warm)

    def test_prewarm_with_new_model_restarts_worker(self):
        self.jobs.submit(Settings(), action="transcribe", text="one")
        until(lambda: len(self.results) == 1)
        first = self.jobs.worker_pid
        self.jobs.prewarm(replace(Settings(), model="qwen-1.7b"))
        until(lambda: self.jobs.warm and not self.jobs.warming)
        self.assertNotEqual(self.jobs.worker_pid, first)

    def test_worker_stderr_and_lifecycle_are_logged(self):
        with self.assertLogs("phimthai.worker", logging.INFO) as logs:
            self.jobs.submit(Settings(), action="transcribe", text="one")
            until(lambda: len(self.results) == 1)
            until(lambda: any("fake worker booting" in line for line in logs.output))
            self.jobs.cancel()
        self.assertTrue(any("worker started pid=" in line for line in logs.output))
        self.assertTrue(any("worker stopped" in line for line in logs.output))


class TimeoutScalingTests(unittest.TestCase):
    def test_timeout_scales_with_wav_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            short, long = Path(directory, "short.wav"), Path(directory, "long.wav")
            write_wav(short, 2)
            write_wav(long, 900, rate=8000)
            self.assertAlmostEqual(audio_seconds(long), 900)
            self.assertEqual(job_timeout_ms({"action": "transcribe", "audio": str(short)}), 600_000)
            self.assertEqual(job_timeout_ms({"action": "transcribe", "audio": str(long)}), (900 * 4 + 120) * 1000)

    def test_non_wav_uses_size_heuristic_and_translate_keeps_default(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory, "audio.ogg")
            raw.write_bytes(b"\1" * 32_000 * 200)
            self.assertEqual(job_timeout_ms({"action": "transcribe", "audio": str(raw)}), (200 * 4 + 120) * 1000)
        self.assertEqual(job_timeout_ms({"action": "translate", "text": "x" * 100_000}), 600_000)
        self.assertEqual(job_timeout_ms({"action": "transcribe", "audio": "/missing.wav"}), 600_000)


if __name__ == "__main__":
    unittest.main()
