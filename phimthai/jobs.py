"""Bounded jobs and parent-owned worker lifecycle for the native application."""
import json
import logging
import os
import signal
import sys
import tempfile
import uuid
import wave
from collections import deque
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Slot

LOG = logging.getLogger("phimthai.worker")
INFERENCE_KEYS = ("model", "device", "language", "cpu_threads", "dictionary", "preference")


def signature_of(settings):
    return json.dumps({key: settings[key] for key in INFERENCE_KEYS}, sort_keys=True)


def audio_seconds(path):
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / (handle.getframerate() or 1)
    except (OSError, EOFError, wave.Error):
        pass
    try:
        # Recorder default: 16 kHz mono Int16. Wider formats overestimate,
        # which only lengthens the timeout.
        return Path(path).stat().st_size / 32_000
    except (OSError, TypeError, ValueError):
        return 0


def job_timeout_ms(job):
    if job.get("action") != "transcribe" or not job.get("audio"):
        return 600_000
    return int(max(600, audio_seconds(job["audio"]) * 4 + 120) * 1000)


class JobController(QObject):
    changed = Signal(str)
    result = Signal(dict)
    failed = Signal(str)
    warm_changed = Signal(bool)

    def __init__(self, parent=None, worker_module="phimthai.worker", temp_root=None):
        super().__init__(parent)
        self.pending = deque()
        self.active = None
        self.process = None
        self.signature = None
        self.buffer = b""
        self.worker_module = worker_module
        self.temp_root = temp_root
        self.worker_temp = None
        self.worker_pid = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)
        # Keep the model loaded between dictations; release RAM when idle.
        self.idle_timeout_ms = 300_000
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self.release_idle)
        self.error_buffer = b""
        self._warm = False

    @property
    def busy(self):
        return bool(self.pending) or (self.active is not None and not self.warming)

    @property
    def warming(self):
        return self.active is not None and self.active.get("action") == "warmup"

    @property
    def warm(self):
        return self._warm and self.process is not None

    ready_model = warm

    def set_warm(self, value):
        if value != self._warm:
            self._warm = value
            self.warm_changed.emit(value)

    def prewarm(self, settings):
        """Load the model in the background (e.g. while recording); never busy, never emits result/failed."""
        settings = asdict(settings)
        if self.active or self.pending or (self.process is not None and signature_of(settings) == self.signature):
            return None
        self.pending.append({"id": uuid.uuid4().hex, "action": "warmup", "settings": settings})
        self.start_next()
        return self.active["id"] if self.warming else None

    def submit(self, settings, **payload):
        if len(self.pending) >= 4:
            raise RuntimeError("Queue is full. Finish or cancel an existing job first.")
        job = dict(payload, id=uuid.uuid4().hex, settings=asdict(settings))
        self.pending.append(job)
        self.start_next()
        return job["id"]

    def start_next(self):
        if self.active:
            return
        if not self.pending:
            # Releasing the owned process also releases Torch/accelerator
            # memory and thread pools, but only after a quiet period.
            if self.process is not None:
                self.idle_timer.start(self.idle_timeout_ms)
            return
        self.idle_timer.stop()
        self.active = self.pending.popleft()
        signature = signature_of(self.active["settings"])
        if signature != self.signature:
            self.stop_worker()
            self.signature = signature
        if self.process is None:
            process = QProcess(self)
            self.process = process
            self.worker_temp = tempfile.TemporaryDirectory(prefix="worker-", dir=self.temp_root)
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("TMPDIR", self.worker_temp.name)
            # Set library limits before imports, including inherited BLAS
            # settings that would otherwise override the selected CPU budget.
            threads = str(self.active["settings"]["cpu_threads"])
            for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
                environment.insert(key, threads)
            process.setProcessEnvironment(environment)
            parameters = QProcess.UnixProcessParameters()
            parameters.flags = QProcess.UnixProcessFlag.CreateNewSession | QProcess.UnixProcessFlag.DisableCoreDumps
            process.setUnixProcessParameters(parameters)
            # QObject receivers avoid closures retaining the parent through a
            # child being deleted during rapid worker teardown/recreation.
            process.started.connect(self.worker_started)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardOutput.connect(self.read_output)
            process.readyReadStandardError.connect(self.read_error)
            process.finished.connect(self.worker_finished)
            process.errorOccurred.connect(self.worker_error)
            process.start(sys.executable, ["-m", self.worker_module])
        else:
            self.dispatch()
        if not self.warming:
            self.changed.emit("กำลังประมวลผลเสียง…")
        self.timer.start(job_timeout_ms(self.active))

    def dispatch(self):
        if self.process is not None and self.active is not None:
            self.process.write((json.dumps(self.active, ensure_ascii=False) + "\n").encode())

    @Slot()
    def worker_started(self):
        process = self.sender()
        if process is self.process:
            self.worker_pid = int(process.processId())
            LOG.info("worker started pid=%s module=%s", self.worker_pid, self.worker_module)

    @Slot()
    def read_error(self):
        process = self.sender()
        data = bytes(process.readAllStandardError())
        if process is not self.process:
            for line in data.decode(errors="replace").splitlines():
                LOG.info("%s", line)
            return
        self.error_buffer += data
        while b"\n" in self.error_buffer:
            line, self.error_buffer = self.error_buffer.split(b"\n", 1)
            if line.strip():
                LOG.info("%s", line.decode(errors="replace").rstrip())

    def flush_error(self):
        if self.error_buffer.strip():
            LOG.info("%s", self.error_buffer.decode(errors="replace").rstrip())
        self.error_buffer = b""

    @Slot()
    def read_output(self):
        process = self.sender()
        if process is not self.process:
            return
        self.buffer += bytes(process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                response = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(response, dict):
                continue
            if response.get("event") == "ready":
                self.dispatch()
            elif self.active and response.get("id") == self.active["id"]:
                self.timer.stop()
                action = self.active.get("action")
                if action == "warmup":
                    self.active = None
                    if response.get("ok"):
                        self.set_warm(True)
                    else:
                        LOG.warning("model warmup failed: %s", response.get("error", "unknown error"))
                    QTimer.singleShot(0, self, self.start_next)
                    continue
                response["settings"] = self.active["settings"]
                if action == "transcribe":
                    response["source_audio"] = self.active.get("audio")
                    if response.get("ok") and response.get("device") != "none":
                        self.set_warm(True)
                self.active = None
                self.changed.emit("Ready")
                if response.get("ok"):
                    self.result.emit(response)
                else:
                    self.failed.emit(response.get("error", "Worker failed"))
                QTimer.singleShot(0, self, self.start_next)

    @Slot(QProcess.ProcessError)
    def worker_error(self, error):
        process = self.sender()
        if process is self.process and error == QProcess.ProcessError.FailedToStart:
            LOG.error("worker failed to start: %s", process.errorString())
            if self.warming and not self.pending:
                self.active = None
                self.timer.stop()
                self.stop_worker()
                return
            self.cancel()
            self.failed.emit("Could not start the speech worker")

    @Slot(int, QProcess.ExitStatus)
    def worker_finished(self, code, status):
        process = self.sender()
        if process is not self.process:
            return
        LOG.info("worker exited code=%s status=%s", code, getattr(status, "name", status))
        self.process = None
        process.deleteLater()
        self.cleanup_worker()
        self.signature = None
        self.buffer = b""
        self.flush_error()
        self.set_warm(False)
        self.timer.stop()
        self.idle_timer.stop()
        if self.warming:
            self.active = None
            LOG.warning("worker stopped during model warmup (%s)", code)
        elif self.active:
            self.active = None
            self.failed.emit(f"Speech worker stopped unexpectedly ({code}). You can retry.")
        QTimer.singleShot(0, self, self.start_next)

    def stop_worker(self):
        process, self.process = self.process, None
        self.buffer = b""
        self.idle_timer.stop()
        if process:
            # Each worker owns its process group, including ffmpeg. Terminate
            # the group before deleting the parent-owned temporary directory.
            self.kill_group()
            process.kill()
            process.waitForFinished(3000)
            LOG.info("worker stopped")
            process.deleteLater()
        self.flush_error()
        self.set_warm(False)
        self.cleanup_worker()

    def release_idle(self):
        if self.active is None and not self.pending:
            LOG.info("releasing idle worker")
            self.stop_worker()

    def kill_group(self):
        if self.worker_pid:
            try:
                os.killpg(self.worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.worker_pid = 0

    def cleanup_worker(self):
        self.kill_group()
        if self.worker_temp:
            self.worker_temp.cleanup()
            self.worker_temp = None

    def cancel(self):
        self.timer.stop()
        self.pending.clear()
        self.active = None
        self.stop_worker()
        self.changed.emit("Cancelled")

    def timeout(self):
        if self.warming:
            LOG.warning("model warmup timed out")
            self.active = None
            self.stop_worker()
            self.start_next()
            return
        self.cancel()
        self.failed.emit("Speech processing timed out. Retry with a shorter recording or another model.")
